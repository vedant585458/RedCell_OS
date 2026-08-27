"""Workspace domain models, Pydantic schemas, and SQLAlchemy ORM entities."""

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.engagement import Base


class WorkspaceStatus(StrEnum):
    """Lifecycle status of a provisioned agent workspace."""

    PROVISIONED = "PROVISIONED"  # Directories created with restrictive permissions
    ACTIVE = "ACTIVE"  # Actively used by worker subprocess
    ARCHIVED = "ARCHIVED"  # Evidence retained, tmp cleared
    CLEANED_UP = "CLEANED_UP"  # Scratchpad purged post-task


class WorkspaceProvisionRequest(BaseModel):
    """Request payload to provision an isolated filesystem workspace."""

    task_id: str = Field(..., description="Task identifier")
    agent_id: str = Field(..., description="Owner AI Employee identifier")
    engagement_id: str = Field(..., description="Parent engagement identifier")
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceResponse(BaseModel):
    """Outbound API response representing a provisioned agent-task workspace."""

    id: str
    task_id: str
    agent_id: str
    engagement_id: str
    workspace_path: str
    tmp_path: str
    artifacts_path: str
    evidence_path: str
    permissions_mode: str
    status: WorkspaceStatus
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


class WorkspaceModel(Base):
    """SQLAlchemy relational table mapping for provisioned Agent Workspaces."""

    __tablename__ = "agent_workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_employees.id"), nullable=False, index=True
    )
    engagement_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("engagements.id"), nullable=False, index=True
    )

    workspace_path: Mapped[str] = mapped_column(String(512), nullable=False)
    tmp_path: Mapped[str] = mapped_column(String(512), nullable=False)
    artifacts_path: Mapped[str] = mapped_column(String(512), nullable=False)
    evidence_path: Mapped[str] = mapped_column(String(512), nullable=False)
    permissions_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="0700")

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=WorkspaceStatus.PROVISIONED.value, index=True
    )
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)

    def to_response(self) -> WorkspaceResponse:
        """Convert ORM model to validated Pydantic WorkspaceResponse."""
        try:
            meta = json.loads(str(self.metadata_json))
        except Exception:
            meta = {}

        return WorkspaceResponse(
            id=str(self.id),
            task_id=str(self.task_id),
            agent_id=str(self.agent_id),
            engagement_id=str(self.engagement_id),
            workspace_path=str(self.workspace_path),
            tmp_path=str(self.tmp_path),
            artifacts_path=str(self.artifacts_path),
            evidence_path=str(self.evidence_path),
            permissions_mode=str(self.permissions_mode),
            status=WorkspaceStatus(str(self.status)),
            metadata=meta,
            created_at=str(self.created_at),
            updated_at=str(self.updated_at),
        )
