"""AgentMemory domain model, Pydantic schemas, and SQLAlchemy ORM entity for persistent per-role long-term memory."""

import json
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.engagement import Base


class MemoryType(StrEnum):
    """Categorical type of learned agent observation or operational pattern."""

    WAF_RULE = "WAF_RULE"  # Web Application Firewall blocking rules or rate thresholds
    TARGET_BEHAVIOR = "TARGET_BEHAVIOR"  # Target server peculiarities, custom 404s, routing traits
    AUTH_MECHANISM = "AUTH_MECHANISM"  # Observed authentication quirks, token formats, headers
    ENVIRONMENT_HEURISTIC = "ENVIRONMENT_HEURISTIC"  # Subnet, OS, or technology stack peculiarities
    TOOL_PARAMETER_TUNING = (
        "TOOL_PARAMETER_TUNING"  # Optimal tool flags, rates, or probe timing for target
    )
    GENERAL = "GENERAL"  # General operational learnings


class MemoryStatus(StrEnum):
    """Lifecycle status of a proposed memory entry."""

    PROPOSED = "PROPOSED"  # Submitted by agent, awaiting heuristic/CISO review
    APPROVED = "APPROVED"  # Validated and approved for injection into future context windows
    REJECTED = "REJECTED"  # Rejected due to poisoning, contradiction, or safety filter failure


class AgentMemoryCreateRequest(BaseModel):
    """Payload to record or propose a new long-term per-role memory entry."""

    id: str = Field(default_factory=lambda: f"mem-{uuid.uuid4().hex[:8]}")
    role_id: str = Field(..., description="Specialist role ID that owns this memory pattern")
    target_domain_or_org: str = Field(
        ..., description="Target domain, IP subnet, or organization name"
    )
    engagement_id: str | None = Field(default=None, description="Optional engagement context")
    memory_type: MemoryType = Field(default=MemoryType.TARGET_BEHAVIOR)
    key: str = Field(..., min_length=2, max_length=128, description="Short identifier key")
    content: str = Field(..., min_length=1, description="Observed pattern or actionable heuristic")
    confidence_score: float = Field(default=0.8, ge=0.0, le=1.0)
    source_task_id: str | None = Field(default=None)
    source_agent_id: str | None = Field(default=None)
    status: MemoryStatus = Field(default=MemoryStatus.PROPOSED)
    approval_notes: str = Field(default="")
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentMemoryResponse(BaseModel):
    """Outbound API response representing an approved or proposed long-term memory entry."""

    id: str
    role_id: str
    target_domain_or_org: str
    engagement_id: str | None
    memory_type: MemoryType
    key: str
    content: str
    confidence_score: float
    source_task_id: str | None
    source_agent_id: str | None
    status: MemoryStatus
    approval_notes: str
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


class AgentMemoryModel(Base):
    """SQLAlchemy relational table mapping for persistent Per-Role Long-Term Memories."""

    __tablename__ = "agent_memories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    role_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("roles.id"), nullable=False, index=True
    )
    target_domain_or_org: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    engagement_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("engagements.id"), nullable=True, index=True
    )

    memory_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default=MemoryType.TARGET_BEHAVIOR.value
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)

    source_task_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("tasks.id"), nullable=True
    )
    source_agent_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("ai_employees.id"), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=MemoryStatus.PROPOSED.value, index=True
    )
    approval_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)

    def to_response(self) -> AgentMemoryResponse:
        """Convert ORM model to validated Pydantic AgentMemoryResponse."""
        try:
            meta = json.loads(str(self.metadata_json))
        except Exception:
            meta = {}

        return AgentMemoryResponse(
            id=str(self.id),
            role_id=str(self.role_id),
            target_domain_or_org=str(self.target_domain_or_org),
            engagement_id=str(self.engagement_id) if self.engagement_id else None,
            memory_type=MemoryType(str(self.memory_type)),
            key=str(self.key),
            content=str(self.content),
            confidence_score=float(self.confidence_score),
            source_task_id=str(self.source_task_id) if self.source_task_id else None,
            source_agent_id=str(self.source_agent_id) if self.source_agent_id else None,
            status=MemoryStatus(str(self.status)),
            approval_notes=str(self.approval_notes),
            metadata=meta,
            created_at=str(self.created_at),
            updated_at=str(self.updated_at),
        )
