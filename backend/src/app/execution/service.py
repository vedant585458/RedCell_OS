"""Mediated Command Execution Service acting as the single secure choke point for all agent tool executions."""

import fnmatch
import ipaddress
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from app.capabilities.registry import CapabilityRegistry, global_capability_registry
from app.core.logging import get_logger
from app.domain.audit import AuditEventCreateRequest
from app.domain.engagement import TargetScopeSchema
from app.domain.execution import CommandRecordSchema, ExecutionCreateRequest
from app.orchestrator.core import global_orchestrator
from app.permissions.checker import PermissionChecker
from app.permissions.models import PermissionCheckRequest
from app.repositories.unit_of_work import UnitOfWork
from app.terminal.session import TerminalSessionManager, global_terminal_manager
from app.tools.registry import ToolRegistry, global_tool_registry
from app.workspace.service import WorkspaceService, global_workspace_service

logger = get_logger("execution.service")


class ExecutionServiceError(Exception):
    """Base exception for mediated command execution failures."""

    pass


class ScopeViolationError(ExecutionServiceError):
    """Raised when an agent attempts to target an out-of-scope or excluded IP, domain, or URI."""

    def __init__(self, target: str, reason: str = "") -> None:
        self.target = target
        self.reason = reason
        super().__init__(
            f"SECURITY ENFORCEMENT BLOCKED: Target '{target}' is OUT OF SCOPE. {reason}"
        )


class SecurityPermissionDeniedError(ExecutionServiceError):
    """Raised when an agent role lacks authorization for a capability or action."""

    def __init__(self, role_id: str, action_or_tool: str, reason: str = "") -> None:
        self.role_id = role_id
        self.action_or_tool = action_or_tool
        self.reason = reason
        super().__init__(
            f"SECURITY PERMISSION DENIED: Role '{role_id}' is not authorized to execute '{action_or_tool}'. {reason}"
        )


class MediatedExecutionResult(BaseModel):
    """Structured result returned by the CommandExecutionService."""

    execution_id: str
    task_id: str
    agent_id: str
    engagement_id: str
    tool_id: str
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_sec: float
    timed_out: bool
    pid: int | None = None
    target: str = ""
    executed_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def validate_target_against_scope(target: str, scope: TargetScopeSchema) -> tuple[bool, str]:
    """Validate whether a target host, IP, or URL is authorized under the engagement Scope rules.

    Checks:
    1. Exclusions (Hard Deny): Explicitly forbidden IPs/CIDRs and domains.
    2. Allowlists (Permit): Authorized CIDRs, domain wildcards, and ports.
    """
    if not target:
        return True, "No network target specified in arguments."

    # Normalize target: extract host from URLs if present
    parsed = urlparse(target if "://" in target else f"//{target}")
    host = (parsed.hostname or target).strip().lower()

    # Check IP vs Domain
    is_ip = False
    try:
        ip_obj = ipaddress.ip_address(host)
        is_ip = True
    except ValueError:
        ip_obj = None

    # --------------------------------------------------------------------------
    # 1. HARD DENY: Check Exclusions
    # --------------------------------------------------------------------------
    if is_ip and ip_obj:
        for exc_cidr in scope.excluded_ipv4_cidrs:
            try:
                if ip_obj in ipaddress.ip_network(exc_cidr, strict=False):
                    return (
                        False,
                        f"Target IP '{host}' falls within excluded CIDR block '{exc_cidr}' (Hard Deny).",
                    )
            except ValueError:
                continue
    else:
        for exc_domain in scope.excluded_domains:
            if fnmatch.fnmatch(host, exc_domain.lower()) or host == exc_domain.lower():
                return (
                    False,
                    f"Target domain '{host}' matches excluded domain pattern '{exc_domain}' (Hard Deny).",
                )

    if parsed.path and scope.excluded_sensitive_endpoints:
        for exc_ep in scope.excluded_sensitive_endpoints:
            if exc_ep.lower() in parsed.path.lower():
                return (
                    False,
                    f"Target path '{parsed.path}' matches excluded sensitive endpoint '{exc_ep}'.",
                )

    # --------------------------------------------------------------------------
    # 2. PERMIT: Check Allowlists (If defined, target must match at least one)
    # --------------------------------------------------------------------------
    has_ip_allowlist = bool(scope.allowed_ipv4_cidrs or scope.allowed_ipv6_cidrs)
    has_domain_allowlist = bool(scope.allowed_domains)

    if not (has_ip_allowlist or has_domain_allowlist):
        return True, "Engagement scope has unrestricted target bounds."

    # Check IP allowlists
    if is_ip and ip_obj:
        matched_cidr = False
        for allow_cidr in scope.allowed_ipv4_cidrs:
            try:
                if ip_obj in ipaddress.ip_network(allow_cidr, strict=False):
                    matched_cidr = True
                    break
            except ValueError:
                continue
        if matched_cidr:
            return True, f"Target IP '{host}' authorized under CIDR '{allow_cidr}'."
        return False, f"Target IP '{host}' does not match any authorized IPv4 CIDR blocks in scope."

    # Check Domain allowlists
    if has_domain_allowlist:
        for allow_domain in scope.allowed_domains:
            if fnmatch.fnmatch(host, allow_domain.lower()) or host == allow_domain.lower():
                return (
                    True,
                    f"Target domain '{host}' matches authorized domain pattern '{allow_domain}'.",
                )
        return (
            False,
            f"Target domain '{host}' does not match any authorized domain allowlists in scope.",
        )

    return False, f"Target '{host}' is not authorized in scope."


class CommandExecutionService:
    """Sole mediated entry point for all agent tool executions.

    Technical Decision (Core Security Control):
    This is the single choke point for all agent tool use — no other code path may spawn agent-driven
    subprocesses. Validates permissions, resolves tools, checks Scope/ROE, and executes via TerminalSession.
    """

    def __init__(
        self,
        session_factory: Any,
        permission_checker: PermissionChecker | None = None,
        tool_registry: ToolRegistry | None = None,
        capability_registry: CapabilityRegistry | None = None,
        workspace_service: WorkspaceService | None = None,
        terminal_manager: TerminalSessionManager | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.permission_checker = permission_checker or PermissionChecker(session_factory)
        self.tool_registry = tool_registry or global_tool_registry
        self.capability_registry = capability_registry or global_capability_registry
        self.workspace_service = workspace_service or global_workspace_service
        self.terminal_manager = terminal_manager or global_terminal_manager

    async def execute(
        self,
        agent_id: str,
        capability: str,
        args: dict[str, Any],
        task_id: str | None = None,
        engagement_id: str | None = None,
        tool_id_override: str | None = None,
        correlation_id: str = "",
    ) -> MediatedExecutionResult:
        """Mediate and execute an agent tool invocation under strict security governance."""
        corr_id = correlation_id or f"corr-exec-{agent_id}-{uuid.uuid4().hex[:6]}"

        # ----------------------------------------------------------------------
        # 1. Fetch Agent, Role, and Engagement Context
        # ----------------------------------------------------------------------
        async with UnitOfWork(self.session_factory) as uow:
            agent = await uow.agents.get_by_id(agent_id)
            if not agent:
                raise ExecutionServiceError(f"AI Employee agent '{agent_id}' not found.")

            role_model = await uow.roles.get_by_id(agent.role_id)
            if not role_model:
                raise ExecutionServiceError(f"Role '{agent.role_id}' not found.")
            role_resp = role_model.to_response()

            effective_task_id = task_id or agent.current_task_id
            if not effective_task_id:
                raise ExecutionServiceError(
                    f"Agent '{agent_id}' has no active task assigned for execution context."
                )

            task_resp = await uow.tasks.get_task_response(effective_task_id)
            if not task_resp:
                raise ExecutionServiceError(f"Task '{effective_task_id}' not found.")

            effective_eng_id = engagement_id or task_resp.engagement_id
            engagement_model = await uow.engagements.get_by_id(effective_eng_id)
            if not engagement_model:
                raise ExecutionServiceError(f"Engagement '{effective_eng_id}' not found.")
            engagement_resp = engagement_model.to_response()

        # ----------------------------------------------------------------------
        # 2. Extract and Validate Target against Engagement Scope (Hard Security Boundary)
        # ----------------------------------------------------------------------
        target_str = str(
            args.get("target")
            or args.get("target_url")
            or args.get("domain")
            or args.get("url")
            or task_resp.input_context.get("target", "")
        )

        in_scope, scope_reason = validate_target_against_scope(
            target=target_str,
            scope=engagement_resp.target_scope,
        )

        if not in_scope:
            # Audit Scope Violation
            logger.warning(
                f"SECURITY VIOLATION BLOCKED: Agent '{agent_id}' attempted out-of-scope target '{target_str}': {scope_reason}",
                agent_id=agent_id,
                target=target_str,
                task_id=effective_task_id,
            )

            async with UnitOfWork(self.session_factory) as uow:
                await uow.audit.append_audit_event(
                    AuditEventCreateRequest(
                        event_id=f"aud-scope-violation-{uuid.uuid4().hex[:8]}",
                        engagement_id=effective_eng_id,
                        correlation_id=corr_id,
                        event_type="scope_violation_blocked",
                        actor_type="AGENT",
                        actor_id=agent_id,
                        payload={
                            "task_id": effective_task_id,
                            "agent_id": agent_id,
                            "target": target_str,
                            "capability": capability,
                            "reason": scope_reason,
                        },
                    )
                )
                await uow.commit()

            await global_orchestrator.emit_event(
                event_type="scope_violation_blocked",
                correlation_id=corr_id,
                engagement_id=effective_eng_id,
                agent_id=agent_id,
                task_id=effective_task_id,
                payload={"target": target_str, "reason": scope_reason},
            )

            raise ScopeViolationError(target=target_str, reason=scope_reason)

        # ----------------------------------------------------------------------
        # 3. Resolve Tool & Check Role Permissions (Deny-by-Default Boundary)
        # ----------------------------------------------------------------------
        # Resolve target tool
        selected_tool = None
        if tool_id_override:
            selected_tool = self.tool_registry.get(tool_id_override)
        else:
            # Match tool from role capabilities
            candidate_tools = self.tool_registry.resolve_tools_for_role(
                role_id=role_resp.id,
                role_capabilities=role_resp.capabilities,
                allowed_tools=role_resp.allowed_tools,
            )
            for tool in candidate_tools:
                if tool.required_capability == capability:
                    selected_tool = tool
                    break
            if not selected_tool and candidate_tools:
                selected_tool = candidate_tools[0]

        if not selected_tool:
            raise SecurityPermissionDeniedError(
                role_id=role_resp.id,
                action_or_tool=capability,
                reason=f"No authorized tool found for capability '{capability}'.",
            )

        # Evaluate permission checker
        action_cat = capability
        perm_result = await self.permission_checker.evaluate_permission(
            PermissionCheckRequest(
                agent_id=agent_id,
                role_id=role_resp.id,
                department_id=agent.department_id,
                tool_id=selected_tool.tool_id,
                target=target_str,
                action_category=action_cat,
                engagement_id=effective_eng_id,
                correlation_id=corr_id,
            )
        )

        if not perm_result.allowed:
            raise SecurityPermissionDeniedError(
                role_id=role_resp.id,
                action_or_tool=selected_tool.tool_id,
                reason=perm_result.reason,
            )

        # ----------------------------------------------------------------------
        # 4. Build Tokenized Command Argv
        # ----------------------------------------------------------------------
        cmd_argv = self.tool_registry.build_command(
            tool_id=selected_tool.tool_id,
            arguments=args,
            allowed_tool_ids=role_resp.allowed_tools,
        )

        # ----------------------------------------------------------------------
        # 5. Provision Workspace & Execute via TerminalSession
        # ----------------------------------------------------------------------
        ws_service = WorkspaceService(self.session_factory)
        workspace = await ws_service.get_workspace_by_task(effective_task_id)
        if not workspace:
            workspace = await ws_service.provision_workspace(
                task_id=effective_task_id,
                agent_id=agent_id,
                engagement_id=effective_eng_id,
                correlation_id=corr_id,
            )

        session = await self.terminal_manager.create_session(
            agent_id=agent_id,
            task_id=effective_task_id,
            engagement_id=effective_eng_id,
            workspace_path=workspace.workspace_path,
        )

        exec_res = await session.execute_command(
            cmd=cmd_argv,
            timeout_sec=selected_tool.default_timeout_sec,
            correlation_id=corr_id,
        )

        # ----------------------------------------------------------------------
        # 6. Persist Command + Execution Telemetry Record
        # ----------------------------------------------------------------------
        exec_id = f"exec-{uuid.uuid4().hex[:8]}"
        async with UnitOfWork(self.session_factory) as uow:
            await uow.executions.record_execution(
                ExecutionCreateRequest(
                    id=exec_id,
                    engagement_id=effective_eng_id,
                    task_id=effective_task_id,
                    agent_id=agent_id,
                    workspace_path=workspace.workspace_path,
                    pid=exec_res.pid or 0,
                    exit_code=exec_res.exit_code,
                    duration_sec=exec_res.duration_sec,
                    timed_out=exec_res.timed_out,
                    command=CommandRecordSchema(
                        raw_command=" ".join(cmd_argv),
                        sanitized_command=" ".join(cmd_argv),
                        target=target_str,
                        tool_name=selected_tool.tool_id,
                    ),
                    stdout_artifact_path="",
                    stderr_artifact_path="",
                )
            )

            # Record audit event
            await uow.audit.append_audit_event(
                AuditEventCreateRequest(
                    event_id=f"aud-cmd-exec-{exec_id[:8]}",
                    engagement_id=effective_eng_id,
                    correlation_id=corr_id,
                    event_type="command_executed",
                    actor_type="AGENT",
                    actor_id=agent_id,
                    payload={
                        "execution_id": exec_id,
                        "task_id": effective_task_id,
                        "tool": selected_tool.tool_id,
                        "command": cmd_argv,
                        "exit_code": exec_res.exit_code,
                        "target": target_str,
                        "duration_sec": exec_res.duration_sec,
                    },
                )
            )
            await uow.commit()

        logger.info(
            f"Mediated command execution complete for agent '{agent_id}': tool '{selected_tool.tool_id}' "
            f"(exit {exec_res.exit_code} in {exec_res.duration_sec:.2f}s)",
            agent_id=agent_id,
            tool=selected_tool.tool_id,
            exit_code=exec_res.exit_code,
        )

        return MediatedExecutionResult(
            execution_id=exec_id,
            task_id=effective_task_id,
            agent_id=agent_id,
            engagement_id=effective_eng_id,
            tool_id=selected_tool.tool_id,
            command=cmd_argv,
            exit_code=exec_res.exit_code,
            stdout=exec_res.stdout,
            stderr=exec_res.stderr,
            duration_sec=exec_res.duration_sec,
            timed_out=exec_res.timed_out,
            pid=exec_res.pid,
            target=target_str,
        )


# Global singleton instance of CommandExecutionService
global_command_execution_service = CommandExecutionService(None)
