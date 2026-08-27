"""Agent failure classification, exponential backoff retry policies, and CISO escalation service."""

import asyncio
import math
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TypeVar

from pydantic import BaseModel, Field

from app.agents.events import AgentLifecycleService
from app.agents.state_machine import AgentLifecycleState
from app.ciso.monitor import CisoProgressMonitor
from app.core.logging import get_logger
from app.domain.audit import AuditEventCreateRequest
from app.domain.task import TaskStatus
from app.orchestrator.core import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork

logger = get_logger("agents.recovery")

T = TypeVar("T")


class FailureClassification(StrEnum):
    """Categorical classification of failures according to retryability."""

    TRANSIENT = "TRANSIENT"  # Temporary failure, eligible for backoff retry
    TERMINAL = "TERMINAL"  # Fatal/irrecoverable failure, immediately escalate or abandon
    UNKNOWN = "UNKNOWN"  # Unrecognized failure, subject to fallback policy


class FailureType(StrEnum):
    """Granular failure types categorized across network, tool execution, permissions, and validation."""

    # Transient types
    NETWORK_TIMEOUT = "network_timeout"
    NETWORK_CONNECTION_ERROR = "network_connection_error"
    RATE_LIMITED = "rate_limited"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_PROCESS_CRASH = "tool_process_crash"
    RESOURCE_UNAVAILABLE = "resource_unavailable"

    # Terminal types
    PERMISSION_DENIED = "permission_denied"
    SCOPE_VIOLATION = "scope_violation"
    VALIDATION_ERROR = "validation_error"
    COMMAND_NOT_FOUND = "command_not_found"
    AUTHENTICATION_ERROR = "authentication_error"
    APPROVAL_REJECTED = "approval_rejected"
    UNEXPECTED_EXCEPTION = "unexpected_exception"


class RecoveryAction(StrEnum):
    """Strategic action determined by the RecoveryPolicy."""

    RETRY = "RETRY"  # Retry operation with backoff delay
    ESCALATE = "ESCALATE"  # Escalate to CISO supervisor / operator for DAG replanning
    ABANDON = "ABANDON"  # Halt execution immediately without replanning


class RecoveryPolicyRule(BaseModel):
    """Configuration rule mapping a failure type to retry and escalation parameters."""

    failure_type: FailureType | str
    classification: FailureClassification
    is_retryable: bool = False
    max_retries: int = Field(default=0, ge=0, le=10)
    base_delay_seconds: float = Field(default=1.0, ge=0.0)
    backoff_factor: float = Field(default=2.0, ge=1.0)
    max_delay_seconds: float = Field(default=30.0, ge=0.0)
    escalate_on_exhaustion: bool = True
    description: str = Field(default="")


class RecoveryDecision(BaseModel):
    """Decision object generated when evaluating an agent failure."""

    decision_id: str = Field(default_factory=lambda: f"rec-{uuid.uuid4().hex[:8]}")
    action: RecoveryAction
    failure_type: FailureType | str
    classification: FailureClassification
    retry_count: int = Field(default=0)
    max_retries: int = Field(default=0)
    delay_seconds: float = Field(default=0.0)
    reason: str
    escalated_to: str | None = None
    error_details: dict[str, Any] = Field(default_factory=dict)
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class RecoveryEscalatedError(Exception):
    """Exception raised when an agent failure cannot be recovered and is escalated."""

    def __init__(self, decision: RecoveryDecision, original_error: Exception | None = None) -> None:
        self.decision = decision
        self.original_error = original_error
        super().__init__(
            f"Agent execution failed and escalated to '{decision.escalated_to or 'CISO'}'. "
            f"Reason: {decision.reason}"
        )


class RecoveryAbandonedError(Exception):
    """Exception raised when an agent failure is permanently abandoned."""

    def __init__(self, decision: RecoveryDecision, original_error: Exception | None = None) -> None:
        self.decision = decision
        self.original_error = original_error
        super().__init__(f"Agent execution abandoned. Reason: {decision.reason}")


# ==============================================================================
# Canonical Default Failure Policy Table
# ==============================================================================

DEFAULT_POLICY_RULES: dict[FailureType, RecoveryPolicyRule] = {
    FailureType.NETWORK_TIMEOUT: RecoveryPolicyRule(
        failure_type=FailureType.NETWORK_TIMEOUT,
        classification=FailureClassification.TRANSIENT,
        is_retryable=True,
        max_retries=3,
        base_delay_seconds=1.0,
        backoff_factor=2.0,
        max_delay_seconds=30.0,
        escalate_on_exhaustion=True,
        description="Transient network or socket timeout",
    ),
    FailureType.NETWORK_CONNECTION_ERROR: RecoveryPolicyRule(
        failure_type=FailureType.NETWORK_CONNECTION_ERROR,
        classification=FailureClassification.TRANSIENT,
        is_retryable=True,
        max_retries=3,
        base_delay_seconds=1.0,
        backoff_factor=2.0,
        max_delay_seconds=30.0,
        escalate_on_exhaustion=True,
        description="Transient network connection reset, refused, or unreachable",
    ),
    FailureType.RATE_LIMITED: RecoveryPolicyRule(
        failure_type=FailureType.RATE_LIMITED,
        classification=FailureClassification.TRANSIENT,
        is_retryable=True,
        max_retries=5,
        base_delay_seconds=2.0,
        backoff_factor=2.0,
        max_delay_seconds=60.0,
        escalate_on_exhaustion=True,
        description="HTTP 429 or provider rate limiting",
    ),
    FailureType.TOOL_TIMEOUT: RecoveryPolicyRule(
        failure_type=FailureType.TOOL_TIMEOUT,
        classification=FailureClassification.TRANSIENT,
        is_retryable=True,
        max_retries=2,
        base_delay_seconds=1.5,
        backoff_factor=2.0,
        max_delay_seconds=20.0,
        escalate_on_exhaustion=True,
        description="Subprocess tool execution exceeded timeout limit",
    ),
    FailureType.RESOURCE_UNAVAILABLE: RecoveryPolicyRule(
        failure_type=FailureType.RESOURCE_UNAVAILABLE,
        classification=FailureClassification.TRANSIENT,
        is_retryable=True,
        max_retries=3,
        base_delay_seconds=1.0,
        backoff_factor=2.0,
        max_delay_seconds=30.0,
        escalate_on_exhaustion=True,
        description="Temporary resource contention, 503 service unavailable, or file lock",
    ),
    FailureType.TOOL_PROCESS_CRASH: RecoveryPolicyRule(
        failure_type=FailureType.TOOL_PROCESS_CRASH,
        classification=FailureClassification.TRANSIENT,
        is_retryable=True,
        max_retries=1,
        base_delay_seconds=1.0,
        backoff_factor=2.0,
        max_delay_seconds=10.0,
        escalate_on_exhaustion=True,
        description="Subprocess tool crashed unexpectedly (e.g. non-zero exit)",
    ),
    FailureType.PERMISSION_DENIED: RecoveryPolicyRule(
        failure_type=FailureType.PERMISSION_DENIED,
        classification=FailureClassification.TERMINAL,
        is_retryable=False,
        max_retries=0,
        base_delay_seconds=0.0,
        escalate_on_exhaustion=True,
        description="Unauthorized capability, tool, or filesystem access denied",
    ),
    FailureType.SCOPE_VIOLATION: RecoveryPolicyRule(
        failure_type=FailureType.SCOPE_VIOLATION,
        classification=FailureClassification.TERMINAL,
        is_retryable=False,
        max_retries=0,
        base_delay_seconds=0.0,
        escalate_on_exhaustion=True,
        description="Target IP/domain is outside authorized Rules of Engagement scope",
    ),
    FailureType.VALIDATION_ERROR: RecoveryPolicyRule(
        failure_type=FailureType.VALIDATION_ERROR,
        classification=FailureClassification.TERMINAL,
        is_retryable=False,
        max_retries=0,
        base_delay_seconds=0.0,
        escalate_on_exhaustion=True,
        description="Invalid parameter schema, malformed JSON, or bad command argument",
    ),
    FailureType.COMMAND_NOT_FOUND: RecoveryPolicyRule(
        failure_type=FailureType.COMMAND_NOT_FOUND,
        classification=FailureClassification.TERMINAL,
        is_retryable=False,
        max_retries=0,
        base_delay_seconds=0.0,
        escalate_on_exhaustion=True,
        description="Subprocess binary or executable not found on system PATH (Exit 127)",
    ),
    FailureType.AUTHENTICATION_ERROR: RecoveryPolicyRule(
        failure_type=FailureType.AUTHENTICATION_ERROR,
        classification=FailureClassification.TERMINAL,
        is_retryable=False,
        max_retries=0,
        base_delay_seconds=0.0,
        escalate_on_exhaustion=True,
        description="Invalid API credentials or authentication failure",
    ),
    FailureType.APPROVAL_REJECTED: RecoveryPolicyRule(
        failure_type=FailureType.APPROVAL_REJECTED,
        classification=FailureClassification.TERMINAL,
        is_retryable=False,
        max_retries=0,
        base_delay_seconds=0.0,
        escalate_on_exhaustion=False,
        description="Human operator rejected gated approval request",
    ),
    FailureType.UNEXPECTED_EXCEPTION: RecoveryPolicyRule(
        failure_type=FailureType.UNEXPECTED_EXCEPTION,
        classification=FailureClassification.TERMINAL,
        is_retryable=False,
        max_retries=0,
        base_delay_seconds=0.0,
        escalate_on_exhaustion=True,
        description="Unclassified fatal runtime exception",
    ),
}


class RecoveryPolicy:
    """Service evaluating failure types, mapping to retry rules, computing backoff, and deciding retry vs escalate."""

    def __init__(
        self, custom_rules: dict[FailureType | str, RecoveryPolicyRule] | None = None
    ) -> None:
        self._rules: dict[str, RecoveryPolicyRule] = {
            k.value if isinstance(k, FailureType) else str(k): v.model_copy()
            for k, v in DEFAULT_POLICY_RULES.items()
        }
        if custom_rules:
            for k, rule in custom_rules.items():
                key = k.value if isinstance(k, FailureType) else str(k)
                self._rules[key] = rule.model_copy()

    def register_rule(self, rule: RecoveryPolicyRule) -> None:
        """Register or override a recovery policy rule."""
        key = (
            rule.failure_type.value
            if isinstance(rule.failure_type, FailureType)
            else str(rule.failure_type)
        )
        self._rules[key] = rule

    def get_rule(self, failure_type: FailureType | str) -> RecoveryPolicyRule:
        """Fetch the rule for a given failure type with fallback to UNEXPECTED_EXCEPTION."""
        key = failure_type.value if isinstance(failure_type, FailureType) else str(failure_type)
        if key in self._rules:
            return self._rules[key]
        return self._rules[FailureType.UNEXPECTED_EXCEPTION.value]

    def classify_failure(
        self,
        error: Exception | str | dict[str, Any] | Any,
        exit_code: int | None = None,
    ) -> tuple[FailureType, FailureClassification]:
        """Classify an exception, error string, or process exit code into FailureType and FailureClassification."""
        # 1. Exit code inspection
        if exit_code is not None:
            if exit_code == 127:
                return FailureType.COMMAND_NOT_FOUND, FailureClassification.TERMINAL
            elif exit_code == 126:
                return FailureType.PERMISSION_DENIED, FailureClassification.TERMINAL
            elif exit_code == 137:
                return FailureType.TOOL_TIMEOUT, FailureClassification.TRANSIENT

        # 2. Python Exception type inspection
        if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
            return FailureType.NETWORK_TIMEOUT, FailureClassification.TRANSIENT
        elif isinstance(
            error, (ConnectionError, ConnectionResetError, ConnectionRefusedError, BrokenPipeError)
        ):
            return FailureType.NETWORK_CONNECTION_ERROR, FailureClassification.TRANSIENT
        elif isinstance(error, PermissionError):
            return FailureType.PERMISSION_DENIED, FailureClassification.TERMINAL
        elif isinstance(error, FileNotFoundError):
            return FailureType.COMMAND_NOT_FOUND, FailureClassification.TERMINAL
        elif isinstance(error, (ValueError, TypeError, KeyError)):
            # Check message details for scope violation
            msg_lower = str(error).lower()
            if any(term in msg_lower for term in ["scope", "roe", "disallowed target"]):
                return FailureType.SCOPE_VIOLATION, FailureClassification.TERMINAL
            return FailureType.VALIDATION_ERROR, FailureClassification.TERMINAL

        # 3. Text pattern inspection across error message / representation
        err_str = str(error).lower()
        if isinstance(error, dict):
            err_str += " " + str(error.get("stderr", "")).lower()
            err_str += " " + str(error.get("message", "")).lower()

        # Regex heuristics for granular matching
        if re.search(r"\b(?:rate\s*limit|429|too\s*many\s*requests)\b", err_str):
            return FailureType.RATE_LIMITED, FailureClassification.TRANSIENT
        if re.search(r"\b(?:timed?\s*out|timeout|deadline\s*exceeded)\b", err_str):
            return FailureType.TOOL_TIMEOUT, FailureClassification.TRANSIENT
        if re.search(
            r"\b(?:connection\s*(?:refused|reset|aborted)|econnreset|network\s*(?:is\s*)?unreachable)\b",
            err_str,
        ):
            return FailureType.NETWORK_CONNECTION_ERROR, FailureClassification.TRANSIENT
        if re.search(
            r"\b(?:resource\s*busy|lock\s*contention|temporarily\s*unavailable|503\s*service\s*unavailable)\b",
            err_str,
        ):
            return FailureType.RESOURCE_UNAVAILABLE, FailureClassification.TRANSIENT
        if re.search(
            r"\b(?:scope\s*violation|out\s*of\s*scope|roe\s*violation|disallowed\s*target)\b",
            err_str,
        ):
            return FailureType.SCOPE_VIOLATION, FailureClassification.TERMINAL
        if re.search(
            r"\b(?:permission\s*denied|forbidden|403\s*forbidden|unauthorized|access\s*denied)\b",
            err_str,
        ):
            return FailureType.PERMISSION_DENIED, FailureClassification.TERMINAL
        if re.search(
            r"\b(?:command\s*not\s*found|no\s*such\s*file\s*or\s*directory|executable\s*not\s*found)\b",
            err_str,
        ):
            return FailureType.COMMAND_NOT_FOUND, FailureClassification.TERMINAL
        if re.search(
            r"\b(?:authentication\s*failed|invalid\s*credentials|api\s*key\s*invalid)\b", err_str
        ):
            return FailureType.AUTHENTICATION_ERROR, FailureClassification.TERMINAL
        if re.search(
            r"\b(?:approval\s*rejected|approval\s*denied|declined\s*by\s*operator)\b", err_str
        ):
            return FailureType.APPROVAL_REJECTED, FailureClassification.TERMINAL
        if re.search(
            r"\b(?:validation\s*error|invalid\s*argument|schema\s*error|parse\s*error|jsondecodeerror)\b",
            err_str,
        ):
            return FailureType.VALIDATION_ERROR, FailureClassification.TERMINAL

        # Check for non-zero process crashes
        if "exit code" in err_str or (exit_code is not None and exit_code != 0):
            return FailureType.TOOL_PROCESS_CRASH, FailureClassification.TRANSIENT

        return FailureType.UNEXPECTED_EXCEPTION, FailureClassification.TERMINAL

    def compute_backoff_delay(
        self,
        attempt: int,
        rule: RecoveryPolicyRule,
        max_delay_cap: float | None = None,
    ) -> float:
        """Compute exponential backoff delay: delay = min(base_delay * (backoff_factor ** attempt), max_delay)."""
        if attempt <= 0:
            return 0.0
        # 0-indexed exponent: attempt 1 uses base_delay * (factor^0) = base_delay
        exponent = attempt - 1
        delay = rule.base_delay_seconds * math.pow(rule.backoff_factor, exponent)
        effective_cap = (
            min(rule.max_delay_seconds, max_delay_cap)
            if max_delay_cap is not None
            else rule.max_delay_seconds
        )
        return min(delay, effective_cap)

    def evaluate_recovery(
        self,
        failure: Exception | str | dict[str, Any] | Any,
        current_retry_count: int = 0,
        exit_code: int | None = None,
        custom_max_retries: int | None = None,
    ) -> RecoveryDecision:
        """Evaluate failure against policy rules and return a RecoveryDecision (RETRY, ESCALATE, or ABANDON)."""
        failure_type, classification = self.classify_failure(failure, exit_code=exit_code)
        rule = self.get_rule(failure_type)

        max_retries = custom_max_retries if custom_max_retries is not None else rule.max_retries

        err_msg = str(failure)
        if isinstance(failure, dict):
            err_msg = failure.get("message") or failure.get("error") or str(failure)

        # 1. Terminal / Non-retryable failure
        if not rule.is_retryable or classification == FailureClassification.TERMINAL:
            action = (
                RecoveryAction.ESCALATE if rule.escalate_on_exhaustion else RecoveryAction.ABANDON
            )
            return RecoveryDecision(
                action=action,
                failure_type=failure_type,
                classification=classification,
                retry_count=current_retry_count,
                max_retries=max_retries,
                delay_seconds=0.0,
                reason=f"Terminal failure '{failure_type}': not retryable. {err_msg}",
                escalated_to="ciso_monitor" if action == RecoveryAction.ESCALATE else None,
                error_details={"raw_error": str(failure), "exit_code": exit_code},
            )

        # 2. Transient failure within retry limit
        if current_retry_count < max_retries:
            next_attempt = current_retry_count + 1
            delay = self.compute_backoff_delay(next_attempt, rule)
            return RecoveryDecision(
                action=RecoveryAction.RETRY,
                failure_type=failure_type,
                classification=classification,
                retry_count=next_attempt,
                max_retries=max_retries,
                delay_seconds=delay,
                reason=(
                    f"Transient failure '{failure_type}': retry attempt {next_attempt}/{max_retries} "
                    f"scheduled with {delay:.2f}s backoff. Error: {err_msg}"
                ),
                error_details={"raw_error": str(failure), "exit_code": exit_code},
            )

        # 3. Transient failure with retries exhausted -> Escalate to CISO monitor
        return RecoveryDecision(
            action=RecoveryAction.ESCALATE,
            failure_type=failure_type,
            classification=classification,
            retry_count=current_retry_count,
            max_retries=max_retries,
            delay_seconds=0.0,
            reason=(
                f"Retries exhausted ({current_retry_count}/{max_retries}) for transient failure "
                f"'{failure_type}'. Escalating to CISO monitor. Last error: {err_msg}"
            ),
            escalated_to="ciso_monitor",
            error_details={"raw_error": str(failure), "exit_code": exit_code},
        )


# ==============================================================================
# Agent Recovery Service
# ==============================================================================


class AgentRecoveryService:
    """Coordinates agent failure handling, FSM state progression, backoff retries, and CISO escalations."""

    def __init__(
        self,
        session_factory: Any,
        policy: RecoveryPolicy | None = None,
        lifecycle_service: AgentLifecycleService | None = None,
        ciso_monitor: CisoProgressMonitor | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.policy = policy or RecoveryPolicy()
        self.lifecycle_service = lifecycle_service or AgentLifecycleService(session_factory)
        self.ciso_monitor = ciso_monitor
        self._retry_counters: dict[str, int] = {}

    def _get_key(self, agent_id: str, task_id: str | None = None) -> str:
        return f"{agent_id}:{task_id or 'default'}"

    def get_retry_count(self, agent_id: str, task_id: str | None = None) -> int:
        """Return current retry attempt count for an agent and task."""
        return self._retry_counters.get(self._get_key(agent_id, task_id), 0)

    def reset_retry_count(self, agent_id: str, task_id: str | None = None) -> None:
        """Reset retry counter on task success or complete cycle."""
        key = self._get_key(agent_id, task_id)
        if key in self._retry_counters:
            del self._retry_counters[key]

    async def handle_agent_failure(
        self,
        agent_id: str,
        error: Exception | str | dict[str, Any] | Any,
        task_id: str | None = None,
        engagement_id: str | None = None,
        correlation_id: str = "",
        exit_code: int | None = None,
        custom_max_retries: int | None = None,
    ) -> RecoveryDecision:
        """Evaluate an agent execution failure, manage FSM transitions, and trigger retry, escalation, or abandonment."""
        key = self._get_key(agent_id, task_id)
        current_retries = self._retry_counters.get(key, 0)

        # 1. Evaluate recovery decision
        decision = self.policy.evaluate_recovery(
            failure=error,
            current_retry_count=current_retries,
            exit_code=exit_code,
            custom_max_retries=custom_max_retries,
        )

        corr_id = correlation_id or f"corr-rec-{agent_id}-{uuid.uuid4().hex[:8]}"

        # 2. Action: RETRY
        if decision.action == RecoveryAction.RETRY:
            self._retry_counters[key] = decision.retry_count

            # FSM: RUNNING -> FAILED -> RECOVERY
            try:
                await self.lifecycle_service.transition_agent_state(
                    agent_id=agent_id,
                    target_state=AgentLifecycleState.FAILED,
                    trigger=f"failure_{decision.failure_type}",
                    correlation_id=corr_id,
                    engagement_id=engagement_id,
                    task_id=task_id,
                    metadata={"error": str(error), "decision": decision.model_dump()},
                )
            except Exception as fsm_err:
                logger.warning(f"FSM transition to FAILED skipped: {fsm_err}")

            try:
                await self.lifecycle_service.transition_agent_state(
                    agent_id=agent_id,
                    target_state=AgentLifecycleState.RECOVERY,
                    trigger=f"retry_backoff_{decision.delay_seconds:.1f}s",
                    correlation_id=corr_id,
                    engagement_id=engagement_id,
                    task_id=task_id,
                    metadata={"decision": decision.model_dump()},
                )
            except Exception as fsm_err:
                logger.warning(f"FSM transition to RECOVERY skipped: {fsm_err}")

            # Emit agent_recovery_attempted event
            await global_orchestrator.emit_event(
                event_type="agent_recovery_attempted",
                correlation_id=corr_id,
                engagement_id=engagement_id,
                agent_id=agent_id,
                task_id=task_id,
                payload=decision.model_dump(),
            )

            logger.info(
                f"Agent '{agent_id}' entering RECOVERY for retry {decision.retry_count}/{decision.max_retries} "
                f"after {decision.delay_seconds:.2f}s delay",
                agent_id=agent_id,
                task_id=task_id,
                retry_count=decision.retry_count,
            )

        # 3. Action: ESCALATE (to CISO monitor)
        elif decision.action == RecoveryAction.ESCALATE:
            # FSM: RUNNING/RECOVERY -> FAILED
            try:
                await self.lifecycle_service.transition_agent_state(
                    agent_id=agent_id,
                    target_state=AgentLifecycleState.FAILED,
                    trigger=f"escalated_{decision.failure_type}",
                    correlation_id=corr_id,
                    engagement_id=engagement_id,
                    task_id=task_id,
                    metadata={"decision": decision.model_dump()},
                )
            except Exception as fsm_err:
                logger.warning(f"FSM transition to FAILED on escalation skipped: {fsm_err}")

            # Update task status in database to FAILED if task_id provided
            if task_id:
                async with UnitOfWork(self.session_factory) as uow:
                    await uow.tasks.update_status(task_id, TaskStatus.FAILED)
                    if engagement_id:
                        await uow.audit.append_audit_event(
                            AuditEventCreateRequest(
                                event_id=f"aud-rec-esc-{uuid.uuid4().hex[:8]}",
                                engagement_id=engagement_id,
                                correlation_id=corr_id,
                                event_type="agent_recovery_escalated",
                                actor_type="AGENT",
                                actor_id=agent_id,
                                payload=decision.model_dump(),
                            )
                        )
                    await uow.commit()

            # Broadcast agent_recovery_escalated event
            await global_orchestrator.emit_event(
                event_type="agent_recovery_escalated",
                correlation_id=corr_id,
                engagement_id=engagement_id,
                agent_id=agent_id,
                task_id=task_id,
                payload=decision.model_dump(),
            )

            # Broadcast task_failed event to orchestrator (which CISO progress monitor listens to)
            task_failed_event = await global_orchestrator.emit_event(
                event_type="task_failed",
                correlation_id=corr_id,
                engagement_id=engagement_id,
                agent_id=agent_id,
                task_id=task_id,
                payload={
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "error": str(error),
                    "failure_type": decision.failure_type,
                    "retry_count": decision.retry_count,
                    "max_retries": decision.max_retries,
                    "reason": decision.reason,
                },
            )

            # If CISO monitor is directly attached, trigger evaluation immediately
            if self.ciso_monitor and engagement_id:
                try:
                    await self.ciso_monitor.handle_event(task_failed_event)
                except Exception as ciso_err:
                    logger.error(f"Error invoking CISO monitor on task failure: {ciso_err}")

            logger.warning(
                f"Agent '{agent_id}' failure escalated to CISO monitor: {decision.reason}",
                agent_id=agent_id,
                task_id=task_id,
                failure_type=decision.failure_type,
            )

        # 4. Action: ABANDON
        elif decision.action == RecoveryAction.ABANDON:
            try:
                await self.lifecycle_service.transition_agent_state(
                    agent_id=agent_id,
                    target_state=AgentLifecycleState.FAILED,
                    trigger=f"abandoned_{decision.failure_type}",
                    correlation_id=corr_id,
                    engagement_id=engagement_id,
                    task_id=task_id,
                    metadata={"decision": decision.model_dump()},
                )
            except Exception:
                pass

            if task_id:
                async with UnitOfWork(self.session_factory) as uow:
                    await uow.tasks.update_status(task_id, TaskStatus.CANCELLED)
                    await uow.commit()

            await global_orchestrator.emit_event(
                event_type="agent_task_abandoned",
                correlation_id=corr_id,
                engagement_id=engagement_id,
                agent_id=agent_id,
                task_id=task_id,
                payload=decision.model_dump(),
            )

        return decision

    async def execute_with_recovery(
        self,
        coro_func: Callable[[], Awaitable[T]],
        agent_id: str,
        task_id: str | None = None,
        engagement_id: str | None = None,
        correlation_id: str = "",
        custom_max_retries: int | None = None,
        sleep_func: Callable[[float], Awaitable[None]] | None = None,
    ) -> T:
        """Execute an asynchronous agent task with self-healing backoff retries and CISO escalation.

        Repeatedly retries transient errors until max_retries is reached, then escalates to CISO monitor.
        Terminal errors escalate immediately without retrying.
        """
        sleeper = sleep_func or asyncio.sleep

        while True:
            try:
                result = await coro_func()
                # On success, reset retry counter
                self.reset_retry_count(agent_id, task_id)
                return result
            except Exception as exc:
                decision = await self.handle_agent_failure(
                    agent_id=agent_id,
                    error=exc,
                    task_id=task_id,
                    engagement_id=engagement_id,
                    correlation_id=correlation_id,
                    custom_max_retries=custom_max_retries,
                )

                if decision.action == RecoveryAction.RETRY:
                    # Delay before retrying
                    if decision.delay_seconds > 0:
                        await sleeper(decision.delay_seconds)
                    # Transition from RECOVERY -> PREPARING -> RUNNING for retry attempt
                    try:
                        await self.lifecycle_service.transition_agent_state(
                            agent_id=agent_id,
                            target_state=AgentLifecycleState.PREPARING,
                            trigger="prepare_retry_attempt",
                            correlation_id=correlation_id,
                            engagement_id=engagement_id,
                            task_id=task_id,
                        )
                        await self.lifecycle_service.transition_agent_state(
                            agent_id=agent_id,
                            target_state=AgentLifecycleState.RUNNING,
                            trigger="resume_running_retry",
                            correlation_id=correlation_id,
                            engagement_id=engagement_id,
                            task_id=task_id,
                        )
                    except Exception as trans_err:
                        logger.warning(f"Error resetting agent state for retry: {trans_err}")
                    continue
                elif decision.action == RecoveryAction.ESCALATE:
                    raise RecoveryEscalatedError(decision, original_error=exc) from exc
                else:  # ABANDON
                    raise RecoveryAbandonedError(decision, original_error=exc) from exc
