"""Permission schemas, role capability flags, and evaluation models."""

from pydantic import BaseModel, Field


class RolePermissionsSchema(BaseModel):
    """Explicit permission flags assigned to an agent role enforced at execution boundary."""

    can_execute_passive_recon: bool = Field(default=False)
    can_execute_active_scan: bool = Field(default=False)
    can_execute_vuln_verification: bool = Field(default=False)
    can_execute_exploit_poc: bool = Field(default=False)
    can_access_internet: bool = Field(default=False)
    can_access_cloud_metadata: bool = Field(default=False)
    can_write_reports: bool = Field(default=False)
    requires_human_approval_for: list[str] = Field(
        default_factory=list,
        description="Approval gate categories requiring mandatory human sign-off",
    )
    max_bandwidth_kbps: int = Field(default=2048, ge=64)
    max_execution_time_sec: int = Field(default=300, ge=10)


class PermissionCheckRequest(BaseModel):
    """Inbound request to evaluate permissions before executing a tool."""

    agent_id: str
    role_id: str
    department_id: str
    tool_id: str
    target: str
    action_category: str = Field(
        default="active_scan",
        description="passive_recon | active_scan | vuln_verification | exploit_poc | cloud_audit | report_compilation",
    )
    engagement_id: str
    task_id: str | None = None
    correlation_id: str


class PermissionEvaluationResult(BaseModel):
    """Result returned by the PermissionChecker service."""

    allowed: bool = Field(description="Whether the requested action is permitted")
    requires_approval: bool = Field(
        default=False, description="Whether the action requires human approval before spawning"
    )
    triggered_gate_category: str | None = Field(default=None)
    reason: str = Field(default="Action permitted under role permissions")
    violating_permission: str | None = Field(default=None)
