"""Command execution and subprocess execution run record domain models."""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.engagement import Base


class CommandRecordSchema(BaseModel):
    """Schema for individual executed shell commands."""

    raw_command: str
    sanitized_command: str
    target: str
    tool_name: str


class ExecutionCreateRequest(BaseModel):
    """Payload to record a completed subprocess tool execution."""

    id: str = Field(default_factory=lambda: f"exec-{uuid.uuid4().hex[:8]}")
    engagement_id: str
    task_id: str
    agent_id: str
    workspace_path: str
    pid: int
    exit_code: int
    stdout_artifact_path: str = Field(default="")
    stderr_artifact_path: str = Field(default="")
    duration_sec: float = Field(ge=0.0)
    timed_out: bool = Field(default=False)
    command: CommandRecordSchema
    started_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ExecutionResponse(BaseModel):
    """Outbound API response representing a process execution run."""

    id: str
    engagement_id: str
    task_id: str
    agent_id: str
    workspace_path: str
    pid: int
    exit_code: int
    stdout_artifact_path: str
    stderr_artifact_path: str
    duration_sec: float
    timed_out: bool
    command: CommandRecordSchema
    started_at: str
    completed_at: str


class ExecutionModel(Base):
    """SQLAlchemy relational table mapping for Process Executions."""

    __tablename__ = "process_executions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    engagement_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("engagements.id"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_employees.id"), nullable=False, index=True
    )

    workspace_path: Mapped[str] = mapped_column(String(256), nullable=False)
    pid: Mapped[int] = mapped_column(Integer, nullable=False)
    exit_code: Mapped[int] = mapped_column(Integer, nullable=False)
    stdout_artifact_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    stderr_artifact_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    duration_sec: Mapped[float] = mapped_column(Float, nullable=False)
    timed_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    raw_command: Mapped[str] = mapped_column(Text, nullable=False)
    sanitized_command: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False, default="cli")

    started_at: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_at: Mapped[str] = mapped_column(String(64), nullable=False)

    def to_response(self) -> ExecutionResponse:
        return ExecutionResponse(
            id=str(self.id),
            engagement_id=str(self.engagement_id),
            task_id=str(self.task_id),
            agent_id=str(self.agent_id),
            workspace_path=str(self.workspace_path),
            pid=int(self.pid),
            exit_code=int(self.exit_code),
            stdout_artifact_path=str(self.stdout_artifact_path),
            stderr_artifact_path=str(self.stderr_artifact_path),
            duration_sec=float(self.duration_sec),
            timed_out=bool(self.timed_out),
            command=CommandRecordSchema(
                raw_command=str(self.raw_command),
                sanitized_command=str(self.sanitized_command),
                target=str(self.target),
                tool_name=str(self.tool_name),
            ),
            started_at=str(self.started_at),
            completed_at=str(self.completed_at),
        )


class ExecutionRepository:
    """Repository managing execution telemetry and tool command history."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    async def record_execution(self, req: ExecutionCreateRequest) -> ExecutionResponse:
        """Create and persist a process execution telemetry record."""
        model = ExecutionModel(
            id=req.id,
            engagement_id=req.engagement_id,
            task_id=req.task_id,
            agent_id=req.agent_id,
            workspace_path=req.workspace_path,
            pid=req.pid,
            exit_code=req.exit_code,
            stdout_artifact_path=req.stdout_artifact_path,
            stderr_artifact_path=req.stderr_artifact_path,
            duration_sec=req.duration_sec,
            timed_out=req.timed_out,
            raw_command=req.command.raw_command,
            sanitized_command=req.command.sanitized_command,
            target=req.command.target,
            tool_name=req.command.tool_name,
            started_at=req.started_at,
            completed_at=req.completed_at,
        )

        async with self.session_factory() as session:
            async with session.begin():
                session.add(model)
            await session.commit()
            return model.to_response()

    async def get_by_id(self, execution_id: str) -> ExecutionResponse | None:
        async with self.session_factory() as session:
            model = await session.get(ExecutionModel, execution_id)
            if model:
                return model.to_response()
            return None

    async def list_by_task(self, task_id: str) -> list[ExecutionResponse]:
        async with self.session_factory() as session:
            from sqlalchemy import select

            stmt = (
                select(ExecutionModel)
                .where(ExecutionModel.task_id == task_id)
                .order_by(ExecutionModel.started_at.asc())
            )
            res = await session.execute(stmt)
            return [row.to_response() for row in res.scalars()]
