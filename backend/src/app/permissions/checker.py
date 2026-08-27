"""PermissionChecker service enforcing deny-by-default role permission models at the execution boundary."""

from typing import Any

from app.capabilities.registry import CapabilityRegistry, global_capability_registry
from app.core.logging import get_logger
from app.domain.audit import AuditEventCreateRequest
from app.orchestrator.core import global_orchestrator
from app.permissions.models import (
    PermissionCheckRequest,
    PermissionEvaluationResult,
    RolePermissionsSchema,
)
from app.repositories.unit_of_work import UnitOfWork
from app.tools.registry import ToolRegistry, global_tool_registry

logger = get_logger("permissions.checker")

# Canonical default permissions mapped to all 16 specialist roles from ROLE_TAXONOMY.md
CANONICAL_ROLE_PERMISSIONS: dict[str, RolePermissionsSchema] = {
    # Executive
    "role_ciso": RolePermissionsSchema(
        can_execute_passive_recon=True,
        can_write_reports=True,
    ),
    "role_engagement_manager": RolePermissionsSchema(
        can_execute_passive_recon=True,
    ),
    # Recon
    "role_passive_osint": RolePermissionsSchema(
        can_execute_passive_recon=True,
        can_access_internet=True,
        can_execute_active_scan=False,
    ),
    "role_active_network_recon": RolePermissionsSchema(
        can_execute_passive_recon=True,
        can_execute_active_scan=True,
        requires_human_approval_for=["HIGH_RATE_FUZZING"],
    ),
    "role_web_discovery": RolePermissionsSchema(
        can_execute_passive_recon=True,
        can_execute_active_scan=True,
    ),
    # Vulnerability
    "role_infra_vuln_assessor": RolePermissionsSchema(
        can_execute_active_scan=True,
        can_execute_vuln_verification=True,
    ),
    "role_web_vuln_assessor": RolePermissionsSchema(
        can_execute_active_scan=True,
        can_execute_vuln_verification=True,
        requires_human_approval_for=["ACTIVE_EXPLOITATION_PROBE"],
    ),
    "role_cloud_container_assessor": RolePermissionsSchema(
        can_execute_active_scan=True,
        can_access_cloud_metadata=True,
        requires_human_approval_for=["CLOUD_RESOURCE_MODIFICATION"],
    ),
    # Exploitation
    "role_exploit_verifier": RolePermissionsSchema(
        can_execute_vuln_verification=True,
        can_execute_exploit_poc=True,
        requires_human_approval_for=["ACTIVE_EXPLOITATION_PROBE"],
    ),
    "role_privesc_credential_analyst": RolePermissionsSchema(
        can_execute_exploit_poc=True,
        requires_human_approval_for=["CREDENTIAL_REUSE_ATTEMPT"],
    ),
    "role_adversary_emulator": RolePermissionsSchema(
        can_execute_exploit_poc=True,
        requires_human_approval_for=["ACTIVE_EXPLOITATION_PROBE", "SUBNET_BOUNDARY_CROSSING"],
    ),
    # Purple & Reporting
    "role_detection_analyst": RolePermissionsSchema(
        can_execute_passive_recon=True,
    ),
    "role_remediation_advisor": RolePermissionsSchema(
        can_write_reports=True,
    ),
    "role_technical_writer": RolePermissionsSchema(
        can_write_reports=True,
        can_execute_active_scan=False,
    ),
    "role_executive_briefer": RolePermissionsSchema(
        can_write_reports=True,
    ),
    "role_safety_sentinel": RolePermissionsSchema(
        can_execute_passive_recon=True,
    ),
}


class PermissionChecker:
    """Service enforcing deny-by-default execution permissions for every tool and action."""

    def __init__(
        self,
        session_factory: Any,
        tool_registry: ToolRegistry | None = None,
        capability_registry: CapabilityRegistry | None = None,
        custom_permissions: dict[str, RolePermissionsSchema] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.tool_registry = tool_registry or global_tool_registry
        self.capability_registry = capability_registry or global_capability_registry
        self.permissions_map = {**CANONICAL_ROLE_PERMISSIONS, **(custom_permissions or {})}

    def get_role_permissions(self, role_id: str) -> RolePermissionsSchema | None:
        """Get permissions configured for a role."""
        return self.permissions_map.get(role_id)

    async def evaluate_permission(self, req: PermissionCheckRequest) -> PermissionEvaluationResult:
        """Evaluate whether an agent is authorized to execute a specific tool action under deny-by-default rules."""
        perms = self.get_role_permissions(req.role_id)

        # 1. Deny-by-default if role permissions not configured
        if not perms:
            reason = f"Security Deny: Role '{req.role_id}' has no configured execution permissions."
            await self._record_violation_audit(req, reason, violating_permission="role_undefined")
            return PermissionEvaluationResult(
                allowed=False,
                reason=reason,
                violating_permission="role_undefined",
            )

        # 2. Verify tool exists in tool registry
        tool = self.tool_registry.get(req.tool_id)
        if not tool:
            reason = f"Security Deny: Tool '{req.tool_id}' is not registered in the tool registry."
            await self._record_violation_audit(
                req, reason, violating_permission="tool_unregistered"
            )
            return PermissionEvaluationResult(
                allowed=False,
                reason=reason,
                violating_permission="tool_unregistered",
            )

        # 3. Action category permission enforcement
        action = req.action_category.lower()

        if action == "active_scan" and not perms.can_execute_active_scan:
            reason = f"Permission Denied: Role '{req.role_id}' is not permitted to execute active network/port scans."
            await self._record_violation_audit(
                req, reason, violating_permission="can_execute_active_scan"
            )
            return PermissionEvaluationResult(
                allowed=False,
                reason=reason,
                violating_permission="can_execute_active_scan",
            )

        if action == "vuln_verification" and not perms.can_execute_vuln_verification:
            reason = f"Permission Denied: Role '{req.role_id}' is not permitted to execute vulnerability verifications."
            await self._record_violation_audit(
                req, reason, violating_permission="can_execute_vuln_verification"
            )
            return PermissionEvaluationResult(
                allowed=False,
                reason=reason,
                violating_permission="can_execute_vuln_verification",
            )

        if action == "exploit_poc" and not perms.can_execute_exploit_poc:
            reason = f"Permission Denied: Role '{req.role_id}' is not permitted to execute exploit proof-of-concept probes."
            await self._record_violation_audit(
                req, reason, violating_permission="can_execute_exploit_poc"
            )
            return PermissionEvaluationResult(
                allowed=False,
                reason=reason,
                violating_permission="can_execute_exploit_poc",
            )

        if action == "cloud_audit" and not perms.can_access_cloud_metadata:
            reason = f"Permission Denied: Role '{req.role_id}' is not permitted to access cloud metadata or IAM APIs."
            await self._record_violation_audit(
                req, reason, violating_permission="can_access_cloud_metadata"
            )
            return PermissionEvaluationResult(
                allowed=False,
                reason=reason,
                violating_permission="can_access_cloud_metadata",
            )

        if action == "report_compilation" and not perms.can_write_reports:
            reason = f"Permission Denied: Role '{req.role_id}' is not permitted to generate final report documents."
            await self._record_violation_audit(
                req, reason, violating_permission="can_write_reports"
            )
            return PermissionEvaluationResult(
                allowed=False,
                reason=reason,
                violating_permission="can_write_reports",
            )

        # 4. Check for Human-in-the-Loop Approval Gate Triggers
        requires_approval = False
        triggered_gate: str | None = None

        # Check tool requirements
        if tool.requires_approval and tool.approval_gate_category:
            requires_approval = True
            triggered_gate = tool.approval_gate_category

        # Check role gate triggers
        for gate_cat in perms.requires_human_approval_for:
            if tool.approval_gate_category == gate_cat or action in gate_cat.lower():
                requires_approval = True
                triggered_gate = gate_cat

        return PermissionEvaluationResult(
            allowed=True,
            requires_approval=requires_approval,
            triggered_gate_category=triggered_gate,
            reason="Action permitted under role permission policy.",
        )

    async def _record_violation_audit(
        self,
        req: PermissionCheckRequest,
        reason: str,
        violating_permission: str,
    ) -> None:
        """Record an immutable security violation audit entry and broadcast alert."""
        logger.warning(
            f"SECURITY PERMISSION BLOCKED: {reason}",
            agent_id=req.agent_id,
            role_id=req.role_id,
            tool_id=req.tool_id,
            target=req.target,
            violating_permission=violating_permission,
        )

        async with UnitOfWork(self.session_factory) as uow:
            await uow.audit.append_audit_event(
                AuditEventCreateRequest(
                    event_id=f"aud-perm-deny-{req.correlation_id}",
                    engagement_id=req.engagement_id,
                    correlation_id=req.correlation_id,
                    event_type="permission_violation_blocked",
                    actor_type="AGENT",
                    actor_id=req.agent_id,
                    payload={
                        "role_id": req.role_id,
                        "department_id": req.department_id,
                        "tool_id": req.tool_id,
                        "target": req.target,
                        "action_category": req.action_category,
                        "violating_permission": violating_permission,
                        "reason": reason,
                    },
                )
            )
            await uow.commit()

        # Emit security alert event
        await global_orchestrator.emit_event(
            event_type="security_permission_blocked",
            correlation_id=req.correlation_id,
            engagement_id=req.engagement_id,
            agent_id=req.agent_id,
            payload={
                "tool_id": req.tool_id,
                "reason": reason,
                "violating_permission": violating_permission,
            },
        )
