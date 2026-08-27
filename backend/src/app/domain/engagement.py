"""Domain models, Pydantic schemas, and SQLAlchemy ORM models for Engagement, Scope, and ROE."""

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base class for SQLAlchemy 2.0 ORM entities."""

    pass


# ==============================================================================
# Pydantic Schemas for Scope, ROE, and API I/O Validation
# ==============================================================================


class TargetScopeSchema(BaseModel):
    """Machine-readable target allowlists and exclusion boundaries."""

    allowed_ipv4_cidrs: list[str] = Field(
        default_factory=list, description="Allowlisted IPv4 CIDR blocks"
    )
    allowed_ipv6_cidrs: list[str] = Field(
        default_factory=list, description="Allowlisted IPv6 CIDR blocks"
    )
    allowed_domains: list[str] = Field(
        default_factory=list, description="Allowlisted target domains (e.g. *.acme.local)"
    )
    allowed_ports: list[str] = Field(
        default_factory=lambda: ["80", "443", "8088"],
        description="Allowed TCP/UDP ports or port ranges",
    )
    allowed_cloud_accounts: list[str] = Field(
        default_factory=list, description="Authorized cloud account IDs"
    )

    # Exclusions (Hard Deny)
    excluded_ipv4_cidrs: list[str] = Field(
        default_factory=list, description="Explicitly forbidden IPv4 addresses or CIDRs"
    )
    excluded_domains: list[str] = Field(
        default_factory=list, description="Explicitly forbidden domains"
    )
    excluded_sensitive_endpoints: list[str] = Field(
        default_factory=list, description="Forbidden API routes or URIs"
    )

    @field_validator("allowed_ipv4_cidrs", "excluded_ipv4_cidrs")
    @classmethod
    def validate_ipv4_cidrs(cls, v: list[str]) -> list[str]:
        cidr_regex = re.compile(r"^([0-9]{1,3}\.){3}[0-9]{1,3}(\/([0-9]|[1-2][0-9]|3[0-2]))?$")
        for cidr in v:
            if not cidr_regex.match(cidr):
                raise ValueError(f"Invalid IPv4/CIDR format: '{cidr}'")
        return v


class RulesOfEngagementSchema(BaseModel):
    """Operational constraints, rate limits, and mandatory approval gates."""

    max_intensity: Literal[
        "passive_recon",
        "active_recon",
        "vulnerability_verification",
        "safe_exploitation",
    ] = Field(
        default="vulnerability_verification",
        description="Maximum permitted offensive intensity",
    )
    allowed_tactics: list[str] = Field(
        default_factory=lambda: ["TA0043", "TA0042", "TA0001", "TA0007"],
        description="Allowed MITRE ATT&CK Tactic IDs",
    )
    prohibited_actions: list[str] = Field(
        default_factory=lambda: [
            "DENIAL_OF_SERVICE",
            "PERMANENT_DESTRUCTION",
            "UNSAFE_CREDENTIAL_SPRAY",
        ],
        description="Explicitly forbidden offensive techniques",
    )
    mandatory_approval_gates: list[str] = Field(
        default_factory=lambda: [
            "ACTIVE_EXPLOITATION_PROBE",
            "CREDENTIAL_REUSE_ATTEMPT",
            "SUBNET_BOUNDARY_CROSSING",
        ],
        description="Categories requiring mandatory human-in-the-loop operator approval",
    )
    max_packets_per_sec: int = Field(default=500, ge=1, le=50000)
    max_concurrent_tasks: int = Field(default=4, ge=1, le=64)
    max_bandwidth_kbps: int = Field(default=4096, ge=64)
    default_gate_timeout_sec: int = Field(default=300, ge=10, le=3600)


class TimeWindowSchema(BaseModel):
    """Temporal validity boundaries for the engagement."""

    valid_from_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    valid_until_utc: str = Field(
        default_factory=lambda: datetime(2030, 1, 1, tzinfo=UTC).isoformat()
    )
    timezone: str = Field(default="UTC")
    emergency_freeze: bool = Field(default=False)


class EngagementCreateRequest(BaseModel):
    """Inbound request payload to initialize a new authorized engagement."""

    engagement_id: str = Field(default_factory=lambda: f"eng-{uuid.uuid4().hex[:8]}")
    title: str = Field(..., min_length=3, max_length=120)
    organization: str = Field(..., min_length=2, max_length=120)
    authorized_by: str = Field(..., min_length=2, max_length=120)
    operator_id: str = Field(default="operator-01")
    time_window: TimeWindowSchema = Field(default_factory=TimeWindowSchema)
    target_scope: TargetScopeSchema = Field(default_factory=TargetScopeSchema)
    rules_of_engagement: RulesOfEngagementSchema = Field(default_factory=RulesOfEngagementSchema)


class EngagementResponse(BaseModel):
    """Outbound API response representing an Engagement entity with nested Scope and ROE."""

    engagement_id: str
    title: str
    status: Literal[
        "CREATED",
        "PLANNING",
        "ACTIVE",
        "PAUSED",
        "COMPLETED",
        "FAILED",
        "EMERGENCY_HALTED",
    ]
    organization: str
    authorized_by: str
    operator_id: str
    time_window: TimeWindowSchema
    target_scope: TargetScopeSchema
    rules_of_engagement: RulesOfEngagementSchema
    created_at: str
    updated_at: str


# ==============================================================================
# SQLAlchemy 2.0 ORM Entity Definition
# ==============================================================================


class EngagementModel(Base):
    """SQLAlchemy relational table mapping for Engagements."""

    __tablename__ = "engagements"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED", index=True)
    organization: Mapped[str] = mapped_column(String(128), nullable=False)
    authorized_by: Mapped[str] = mapped_column(String(128), nullable=False)
    operator_id: Mapped[str] = mapped_column(String(64), nullable=False)

    valid_from_utc: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_until_utc: Mapped[str] = mapped_column(String(64), nullable=False)
    timezone: Mapped[str] = mapped_column(String(32), nullable=False, default="UTC")
    emergency_freeze: Mapped[str] = mapped_column(String(8), nullable=False, default="false")

    target_scope_json: Mapped[str] = mapped_column(Text, nullable=False)
    rules_of_engagement_json: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)

    def to_response(self) -> EngagementResponse:
        """Convert ORM model to validated Pydantic EngagementResponse."""
        try:
            scope_dict = json.loads(str(self.target_scope_json))
        except Exception:
            scope_dict = {}

        try:
            roe_dict = json.loads(str(self.rules_of_engagement_json))
        except Exception:
            roe_dict = {}

        return EngagementResponse(
            engagement_id=str(self.id),
            title=str(self.title),
            status=str(self.status),  # type: ignore[arg-type]
            organization=str(self.organization),
            authorized_by=str(self.authorized_by),
            operator_id=str(self.operator_id),
            time_window=TimeWindowSchema(
                valid_from_utc=str(self.valid_from_utc),
                valid_until_utc=str(self.valid_until_utc),
                timezone=str(self.timezone),
                emergency_freeze=str(self.emergency_freeze).lower() == "true",
            ),
            target_scope=TargetScopeSchema(**scope_dict),
            rules_of_engagement=RulesOfEngagementSchema(**roe_dict),
            created_at=str(self.created_at),
            updated_at=str(self.updated_at),
        )


# ==============================================================================
# Repository Layer for Engagement / Scope / ROE Data Access
# ==============================================================================


class EngagementRepository:
    """Repository handling CRUD transactions for Engagements, Scope, and ROE."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    async def create(self, req: EngagementCreateRequest) -> EngagementResponse:
        """Create and persist a new engagement with nested scope and ROE."""
        now = datetime.now(UTC).isoformat()

        model = EngagementModel(
            id=req.engagement_id,
            title=req.title,
            status="CREATED",
            organization=req.organization,
            authorized_by=req.authorized_by,
            operator_id=req.operator_id,
            valid_from_utc=req.time_window.valid_from_utc,
            valid_until_utc=req.time_window.valid_until_utc,
            timezone=req.time_window.timezone,
            emergency_freeze="true" if req.time_window.emergency_freeze else "false",
            target_scope_json=json.dumps(req.target_scope.model_dump()),
            rules_of_engagement_json=json.dumps(req.rules_of_engagement.model_dump()),
            created_at=now,
            updated_at=now,
        )

        async with self.session_factory() as session:
            async with session.begin():
                session.add(model)
            await session.commit()
            return model.to_response()

    async def get_by_id(self, engagement_id: str) -> EngagementResponse | None:
        """Fetch an engagement by its unique ID."""
        async with self.session_factory() as session:
            model = await session.get(EngagementModel, engagement_id)
            if model:
                return model.to_response()
            return None

    async def update_status(self, engagement_id: str, status: str) -> EngagementResponse | None:
        """Update lifecycle status of an engagement."""
        async with self.session_factory() as session:
            async with session.begin():
                model = await session.get(EngagementModel, engagement_id)
                if not model:
                    return None
                model.status = status
                model.updated_at = datetime.now(UTC).isoformat()
            await session.commit()
            return model.to_response()
