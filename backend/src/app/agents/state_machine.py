"""Explicit Finite-State Machine (FSM) for AI Employee agent execution lifecycles."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger

logger = get_logger("agents.fsm")


class AgentLifecycleState(StrEnum):
    """Full lifecycle states for AI Employees matching agent_execution specification."""

    IDLE = "idle"  # Available, waiting for tasks
    PLANNING = "planning"  # Analyzing task context and tool options
    ASSIGNED = "assigned"  # Task assigned by orchestrator
    PREPARING = "preparing"  # Setting up workspace scratchpad and parameters
    RUNNING = "running"  # Actively executing tool subprocess or probe
    WAITING_BLOCKED = "waiting_blocked"  # Paused on approval gate or external resource
    COMMUNICATION = "communication"  # Briefing, messaging, or handoff with sibling agent
    REVIEW = "review"  # Self-reviewing finding quality or execution artifact
    COMPLETED = "completed"  # Successfully finished task
    FAILED = "failed"  # Tool or execution error
    RECOVERY = "recovery"  # Attempting self-healing rollback or retry
    TERMINATION = "termination"  # Terminated by operator or kill switch


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal or invalid state transition is attempted."""

    def __init__(
        self,
        from_state: AgentLifecycleState,
        to_state: AgentLifecycleState,
        agent_id: str,
        reason: str = "",
    ) -> None:
        self.from_state = from_state
        self.to_state = to_state
        self.agent_id = agent_id
        self.reason = reason
        msg = f"Invalid FSM transition for agent '{agent_id}': cannot transition from '{from_state}' to '{to_state}'."
        if reason:
            msg += f" Reason: {reason}"
        super().__init__(msg)


# Centralized transition table defining strictly allowed FSM transitions
ALLOWED_TRANSITIONS: dict[AgentLifecycleState, set[AgentLifecycleState]] = {
    AgentLifecycleState.IDLE: {
        AgentLifecycleState.PLANNING,
        AgentLifecycleState.ASSIGNED,
        AgentLifecycleState.TERMINATION,
    },
    AgentLifecycleState.PLANNING: {
        AgentLifecycleState.ASSIGNED,
        AgentLifecycleState.PREPARING,
        AgentLifecycleState.WAITING_BLOCKED,
        AgentLifecycleState.COMMUNICATION,
        AgentLifecycleState.FAILED,
        AgentLifecycleState.IDLE,
        AgentLifecycleState.TERMINATION,
    },
    AgentLifecycleState.ASSIGNED: {
        AgentLifecycleState.PREPARING,
        AgentLifecycleState.PLANNING,
        AgentLifecycleState.WAITING_BLOCKED,
        AgentLifecycleState.FAILED,
        AgentLifecycleState.IDLE,
        AgentLifecycleState.TERMINATION,
    },
    AgentLifecycleState.PREPARING: {
        AgentLifecycleState.RUNNING,
        AgentLifecycleState.WAITING_BLOCKED,
        AgentLifecycleState.COMMUNICATION,
        AgentLifecycleState.FAILED,
        AgentLifecycleState.TERMINATION,
    },
    AgentLifecycleState.RUNNING: {
        AgentLifecycleState.WAITING_BLOCKED,
        AgentLifecycleState.COMMUNICATION,
        AgentLifecycleState.REVIEW,
        AgentLifecycleState.COMPLETED,
        AgentLifecycleState.FAILED,
        AgentLifecycleState.TERMINATION,
    },
    AgentLifecycleState.WAITING_BLOCKED: {
        AgentLifecycleState.RUNNING,
        AgentLifecycleState.PREPARING,
        AgentLifecycleState.PLANNING,
        AgentLifecycleState.FAILED,
        AgentLifecycleState.TERMINATION,
    },
    AgentLifecycleState.COMMUNICATION: {
        AgentLifecycleState.RUNNING,
        AgentLifecycleState.REVIEW,
        AgentLifecycleState.PLANNING,
        AgentLifecycleState.PREPARING,
        AgentLifecycleState.FAILED,
        AgentLifecycleState.TERMINATION,
    },
    AgentLifecycleState.REVIEW: {
        AgentLifecycleState.COMPLETED,
        AgentLifecycleState.FAILED,
        AgentLifecycleState.PLANNING,
        AgentLifecycleState.COMMUNICATION,
        AgentLifecycleState.TERMINATION,
    },
    AgentLifecycleState.COMPLETED: {
        AgentLifecycleState.IDLE,
        AgentLifecycleState.PLANNING,
        AgentLifecycleState.TERMINATION,
    },
    AgentLifecycleState.FAILED: {
        AgentLifecycleState.RECOVERY,
        AgentLifecycleState.TERMINATION,
        AgentLifecycleState.IDLE,
    },
    AgentLifecycleState.RECOVERY: {
        AgentLifecycleState.IDLE,
        AgentLifecycleState.PLANNING,
        AgentLifecycleState.PREPARING,
        AgentLifecycleState.FAILED,
        AgentLifecycleState.TERMINATION,
    },
    AgentLifecycleState.TERMINATION: {
        AgentLifecycleState.IDLE,  # Re-initialization
    },
}


class StateTransitionRecord(BaseModel):
    """Immutable record capturing an FSM state transition."""

    agent_id: str
    from_state: AgentLifecycleState
    to_state: AgentLifecycleState
    trigger: str = Field(default="")
    correlation_id: str = Field(default="")
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


TransitionCallback = (
    Callable[[StateTransitionRecord], Awaitable[None]] | Callable[[StateTransitionRecord], None]
)


class AgentStateMachine:
    """Explicit FSM engine validating transitions, logging history, and notifying listeners."""

    def __init__(
        self,
        agent_id: str,
        initial_state: AgentLifecycleState = AgentLifecycleState.IDLE,
        on_transition: TransitionCallback | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.current_state = initial_state
        self.on_transition = on_transition
        self.history: list[StateTransitionRecord] = []
        self.current_task_id: str | None = None

    def can_transition_to(self, target_state: AgentLifecycleState) -> bool:
        """Check if transitioning from current state to target state is legally permitted."""
        allowed_targets = ALLOWED_TRANSITIONS.get(self.current_state, set())
        return target_state in allowed_targets

    def transition_to(
        self,
        target_state: AgentLifecycleState,
        trigger: str = "",
        correlation_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> StateTransitionRecord:
        """Execute a state transition, raising InvalidStateTransitionError on disallowed paths."""
        if not self.can_transition_to(target_state):
            logger.error(
                "Illegal FSM transition attempted",
                agent_id=self.agent_id,
                from_state=self.current_state,
                to_state=target_state,
                trigger=trigger,
            )
            raise InvalidStateTransitionError(
                from_state=self.current_state,
                to_state=target_state,
                agent_id=self.agent_id,
                reason=f"Transition not allowed in transition table. Valid targets from '{self.current_state}' are: {[s.value for s in ALLOWED_TRANSITIONS.get(self.current_state, set())]}",
            )

        from_state = self.current_state
        self.current_state = target_state

        record = StateTransitionRecord(
            agent_id=self.agent_id,
            from_state=from_state,
            to_state=target_state,
            trigger=trigger,
            correlation_id=correlation_id,
            metadata=metadata or {},
        )
        self.history.append(record)

        logger.debug(
            "Agent FSM transition succeeded",
            agent_id=self.agent_id,
            from_state=from_state,
            to_state=target_state,
            trigger=trigger,
        )

        if self.on_transition:
            try:
                res = self.on_transition(record)
                if hasattr(res, "__await__"):
                    import asyncio

                    asyncio.create_task(res)  # type: ignore[arg-type]
            except Exception as err:
                logger.warning(f"Error in on_transition callback: {err}")

        return record

    # High-level domain transition helpers
    def assign_task(self, task_id: str, correlation_id: str = "") -> StateTransitionRecord:
        self.current_task_id = task_id
        return self.transition_to(
            AgentLifecycleState.ASSIGNED,
            trigger="task_assigned",
            correlation_id=correlation_id,
            metadata={"task_id": task_id},
        )

    def start_planning(self, correlation_id: str = "") -> StateTransitionRecord:
        return self.transition_to(
            AgentLifecycleState.PLANNING,
            trigger="start_planning",
            correlation_id=correlation_id,
        )

    def start_preparing(self, correlation_id: str = "") -> StateTransitionRecord:
        return self.transition_to(
            AgentLifecycleState.PREPARING,
            trigger="start_preparing",
            correlation_id=correlation_id,
        )

    def start_running(self, correlation_id: str = "") -> StateTransitionRecord:
        return self.transition_to(
            AgentLifecycleState.RUNNING,
            trigger="start_running",
            correlation_id=correlation_id,
        )

    def wait_for_approval(self, gate_id: str, correlation_id: str = "") -> StateTransitionRecord:
        return self.transition_to(
            AgentLifecycleState.WAITING_BLOCKED,
            trigger="approval_required",
            correlation_id=correlation_id,
            metadata={"gate_id": gate_id},
        )

    def enter_communication(
        self, recipient_id: str, correlation_id: str = ""
    ) -> StateTransitionRecord:
        return self.transition_to(
            AgentLifecycleState.COMMUNICATION,
            trigger="inter_agent_communication",
            correlation_id=correlation_id,
            metadata={"recipient_id": recipient_id},
        )

    def enter_review(self, correlation_id: str = "") -> StateTransitionRecord:
        return self.transition_to(
            AgentLifecycleState.REVIEW,
            trigger="finding_quality_review",
            correlation_id=correlation_id,
        )

    def mark_completed(self, correlation_id: str = "") -> StateTransitionRecord:
        return self.transition_to(
            AgentLifecycleState.COMPLETED,
            trigger="task_completed_success",
            correlation_id=correlation_id,
        )

    def mark_failed(self, error_message: str, correlation_id: str = "") -> StateTransitionRecord:
        return self.transition_to(
            AgentLifecycleState.FAILED,
            trigger="execution_error",
            correlation_id=correlation_id,
            metadata={"error": error_message},
        )

    def start_recovery(self, correlation_id: str = "") -> StateTransitionRecord:
        return self.transition_to(
            AgentLifecycleState.RECOVERY,
            trigger="start_error_recovery",
            correlation_id=correlation_id,
        )

    def terminate(
        self, reason: str = "emergency_kill", correlation_id: str = ""
    ) -> StateTransitionRecord:
        return self.transition_to(
            AgentLifecycleState.TERMINATION,
            trigger=reason,
            correlation_id=correlation_id,
            metadata={"reason": reason},
        )
