"""ExecutionContext domain models, Pydantic schemas, and SQLAlchemy ORM entities."""

import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.engagement import Base


class ExecutionContextStatus(StrEnum):
    """Lifecycle status of an agent's working execution context."""

    INITIALIZED = "INITIALIZED"  # Created at task assignment
    ACTIVE = "ACTIVE"  # Actively executing tool actions and receiving messages
    COMPLETED = "COMPLETED"  # Task finished successfully
    FAILED = "FAILED"  # Task failed
    ARCHIVED = "ARCHIVED"  # Pruned and committed to persistent audit store


class CommandExecutionRecord(BaseModel):
    """Record of a tool subprocess or probe executed during the context lifecycle."""

    command_id: str = Field(default_factory=lambda: f"cmd-{uuid.uuid4().hex[:8]}")
    command: list[str]
    exit_code: int
    stdout_snippet: str = Field(default="")
    stderr_snippet: str = Field(default="")
    duration_sec: float = Field(default=0.0)
    executed_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ExecutionContextArchive(BaseModel):
    """Pruned and structured archive record of an agent's execution context for long-term audit."""

    context_id: str
    task_id: str
    agent_id: str
    role_id: str
    engagement_id: str
    department_id: str
    final_status: str
    total_commands_executed: int
    total_llm_turns: int
    findings_count: int
    discovered_finding_ids: list[str] = Field(default_factory=list)
    approval_gate_records: list[dict[str, Any]] = Field(default_factory=list)
    pruned_messages: list[dict[str, Any]] = Field(default_factory=list)
    executed_commands: list[dict[str, Any]] = Field(default_factory=list)
    scratchpad_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    closed_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    archived_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ExecutionContextModel(Base):
    """SQLAlchemy relational table mapping for archived Agent Execution Contexts."""

    __tablename__ = "execution_contexts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_employees.id"), nullable=False, index=True
    )
    role_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("roles.id"), nullable=False, index=True
    )
    engagement_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("engagements.id"), nullable=False, index=True
    )
    department_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("departments.id"), nullable=False, index=True
    )
    final_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    archive_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    closed_at: Mapped[str] = mapped_column(String(64), nullable=False)

    def to_archive(self) -> ExecutionContextArchive:
        """Convert ORM model to validated ExecutionContextArchive."""
        try:
            data = json.loads(str(self.archive_payload_json))
            return ExecutionContextArchive(**data)
        except Exception:
            return ExecutionContextArchive(
                context_id=str(self.id),
                task_id=str(self.task_id),
                agent_id=str(self.agent_id),
                role_id=str(self.role_id),
                engagement_id=str(self.engagement_id),
                department_id=str(self.department_id),
                final_status=str(self.final_status),
                total_commands_executed=0,
                total_llm_turns=0,
                findings_count=0,
                created_at=str(self.created_at),
                closed_at=str(self.closed_at),
            )
