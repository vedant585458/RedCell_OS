"""Engagement intake and ROE validation service for RedCell_OS."""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.domain.audit import AuditEventCreateRequest
from app.domain.engagement import (
    EngagementCreateRequest,
    EngagementResponse,
    RulesOfEngagementSchema,
    TargetScopeSchema,
    TimeWindowSchema,
)
from app.orchestrator.core import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork

logger = get_logger("services.intake")


class EngagementIntakeRequest(BaseModel):
    """Structured intake request submitted by operator to initialize an engagement."""

    engagement_id: str = Field(default_factory=lambda: f"eng-{uuid.uuid4().hex[:8]}")
    title: str = Field(
        ..., min_length=3, max_length=120, description="Engagement title / mission name"
    )
    organization: str = Field(
        ..., min_length=2, max_length=120, description="Target enterprise organization name"
    )
    authorized_by: str = Field(
        ..., min_length=2, max_length=120, description="Name and title of authorizing executive"
    )
    operator_id: str = Field(
        default="operator-01", description="Operator identity handling execution"
    )
    high_level_objective: str = Field(
        default="Conduct authorized penetration testing assessment against allowlisted attack surface.",
        description="High-level mission goals and objectives for the CISO agent",
    )
    time_window: TimeWindowSchema = Field(default_factory=TimeWindowSchema)
    target_scope: TargetScopeSchema = Field(
        ..., description="Mandatory machine-readable target allowlist and exclusions (M002)"
    )
    rules_of_engagement: RulesOfEngagementSchema = Field(default_factory=RulesOfEngagementSchema)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EngagementIntakeService:
    """Service validating Rules of Engagement (ROE) and bootstrapping new engagements."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    def validate_roe_scope(self, req: EngagementIntakeRequest) -> None:
        """Validate that the structured Rules of Engagement (ROE) has non-empty target boundaries."""
        scope = req.target_scope

        # Ensure at least one target identifier is specified
        has_targets = bool(
            scope.allowed_ipv4_cidrs
            or scope.allowed_ipv6_cidrs
            or scope.allowed_domains
            or scope.allowed_cloud_accounts
        )
        if not has_targets:
            raise ValueError(
                "Invalid Scope: At least one allowlisted target (IPv4 CIDR, IPv6 CIDR, Domain, or Cloud Account) must be specified."
            )

        # Ensure allowed ports are provided
        if not scope.allowed_ports:
            raise ValueError(
                "Invalid Scope: At least one target port or port range must be allowlisted."
            )

    async def intake_engagement(self, req: EngagementIntakeRequest) -> EngagementResponse:
        """Validate, persist, audit, and emit event for a new engagement."""
        # 1. Enforce machine-readable ROE constraints (M002)
        self.validate_roe_scope(req)

        create_req = EngagementCreateRequest(
            engagement_id=req.engagement_id,
            title=req.title,
            organization=req.organization,
            authorized_by=req.authorized_by,
            operator_id=req.operator_id,
            time_window=req.time_window,
            target_scope=req.target_scope,
            rules_of_engagement=req.rules_of_engagement,
        )

        # 2. Persist to relational database and append cryptographic audit log
        async with UnitOfWork(self.session_factory) as uow:
            engagement_resp = await uow.engagements.create_engagement(create_req)

            # Record in immutable audit log
            await uow.audit.append_audit_event(
                AuditEventCreateRequest(
                    event_id=f"aud-intake-{req.engagement_id}",
                    engagement_id=req.engagement_id,
                    correlation_id=f"corr-{req.engagement_id}",
                    event_type="engagement_created",
                    actor_type="OPERATOR",
                    actor_id=req.operator_id,
                    payload={
                        "title": req.title,
                        "organization": req.organization,
                        "authorized_by": req.authorized_by,
                        "objective": req.high_level_objective,
                        "allowed_cidrs": req.target_scope.allowed_ipv4_cidrs,
                        "allowed_domains": req.target_scope.allowed_domains,
                        "allowed_ports": req.target_scope.allowed_ports,
                        "max_intensity": req.rules_of_engagement.max_intensity,
                    },
                )
            )
            await uow.commit()

        logger.info(
            "Engagement intake completed successfully",
            engagement_id=req.engagement_id,
            title=req.title,
            organization=req.organization,
        )

        # 3. Emit real-time event to orchestrator event bus (broadcasts to WebSocket clients)
        await global_orchestrator.emit_event(
            event_type="engagement_created",
            correlation_id=f"corr-{req.engagement_id}",
            engagement_id=req.engagement_id,
            payload={
                "engagement_id": req.engagement_id,
                "title": req.title,
                "organization": req.organization,
                "status": "CREATED",
                "objective": req.high_level_objective,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )

        return engagement_resp
