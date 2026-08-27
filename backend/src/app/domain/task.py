"""Task and TaskDependency domain models, Pydantic schemas, and SQLAlchemy ORM entities."""

import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.engagement import Base


class TaskStatus(StrEnum):
    """Lifecycle status enum for individual tasks within an engagement DAG."""

    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class TaskPriority(int):
    """Task execution priority levels."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class TaskCreateRequest(BaseModel):
    """Payload to create a new task within an engagement Directed Acyclic Graph (DAG)."""

    task_id: str = Field(default_factory=lambda: f"task-{uuid.uuid4().hex[:8]}")
    engagement_id: str = Field(..., description="Parent engagement identifier")
    department_id: str = Field(..., description="Executing department identifier")
    title: str = Field(..., min_length=2, max_length=128)
    description: str = Field(default="")
    priority: int = Field(default=2, ge=1, le=4)
    assigned_role: str = Field(
        ..., description="Required specialist role identifier (e.g. role_web_discovery)"
    )
    assigned_agent_id: str | None = Field(default=None)
    parent_task_id: str | None = Field(default=None)
    depends_on: list[str] = Field(default_factory=list, description="List of prerequisite task IDs")
    requires_approval_gate: str | None = Field(
        default=None, description="Triggered approval gate category if gated"
    )
    input_context: dict[str, Any] = Field(
        default_factory=dict, description="Input parameters and targets"
    )


class TaskUpdateRequest(BaseModel):
    """Payload to update task status or execution results."""

    status: TaskStatus | None = None
    assigned_agent_id: str | None = None
    output_artifacts: list[dict[str, Any]] | None = None
    result_summary: str | None = None


class TaskResponse(BaseModel):
    """Outbound API response representing a Task entity and its dependency graph edges."""

    task_id: str
    engagement_id: str
    department_id: str
    title: str
    description: str
    status: TaskStatus
    priority: int
    assigned_role: str
    assigned_agent_id: str | None
    parent_task_id: str | None
    depends_on: list[str]
    blocks: list[str]
    requires_approval_gate: str | None
    input_context: dict[str, Any]
    output_artifacts: list[dict[str, Any]]
    created_at: str
    updated_at: str


# ==============================================================================
# SQLAlchemy 2.0 ORM Entity Definitions
# ==============================================================================


class TaskModel(Base):
    """SQLAlchemy relational table mapping for discrete Engagement Tasks."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    engagement_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("engagements.id"), nullable=False, index=True
    )
    department_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("departments.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=TaskStatus.PENDING.value, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=2)

    assigned_role: Mapped[str] = mapped_column(String(64), nullable=False)
    assigned_agent_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("ai_employees.id"), nullable=True, index=True
    )
    parent_task_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("tasks.id"), nullable=True, index=True
    )

    requires_approval_gate: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_context_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    output_artifacts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)

    def to_response(
        self, depends_on: list[str] | None = None, blocks: list[str] | None = None
    ) -> TaskResponse:
        """Convert ORM model to validated Pydantic TaskResponse."""
        try:
            input_context = json.loads(str(self.input_context_json))
        except Exception:
            input_context = {}

        try:
            output_artifacts = json.loads(str(self.output_artifacts_json))
        except Exception:
            output_artifacts = []

        return TaskResponse(
            task_id=str(self.id),
            engagement_id=str(self.engagement_id),
            department_id=str(self.department_id),
            title=str(self.title),
            description=str(self.description),
            status=TaskStatus(str(self.status)),
            priority=int(self.priority),
            assigned_role=str(self.assigned_role),
            assigned_agent_id=str(self.assigned_agent_id) if self.assigned_agent_id else None,
            parent_task_id=str(self.parent_task_id) if self.parent_task_id else None,
            depends_on=depends_on or [],
            blocks=blocks or [],
            requires_approval_gate=str(self.requires_approval_gate)
            if self.requires_approval_gate
            else None,
            input_context=input_context,
            output_artifacts=output_artifacts,
            created_at=str(self.created_at),
            updated_at=str(self.updated_at),
        )


class TaskDependencyModel(Base):
    """SQLAlchemy edge table mapping task dependencies (task_id depends on depends_on_task_id)."""

    __tablename__ = "task_dependencies"

    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )

    __table_args__ = (
        CheckConstraint("task_id != depends_on_task_id", name="check_prevent_self_dependency"),
        Index("idx_task_deps_lookup", "task_id", "depends_on_task_id"),
        Index("idx_task_deps_reverse", "depends_on_task_id", "task_id"),
    )


# ==============================================================================
# Repository Layer for Tasks & Graph Dependencies
# ==============================================================================


class TaskRepository:
    """Repository managing Task CRUD and Directed Acyclic Graph (DAG) dependency edges."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    async def create_task(self, req: TaskCreateRequest) -> TaskResponse:
        """Create and persist a task along with its prerequisite dependency edges."""
        # Self-dependency check at application layer before DB transaction
        if req.task_id in req.depends_on:
            raise ValueError(
                f"Self-dependency detected: Task '{req.task_id}' cannot depend on itself."
            )

        now = datetime.now(UTC).isoformat()
        task_model = TaskModel(
            id=req.task_id,
            engagement_id=req.engagement_id,
            department_id=req.department_id,
            title=req.title,
            description=req.description,
            status=TaskStatus.PENDING.value,
            priority=req.priority,
            assigned_role=req.assigned_role,
            assigned_agent_id=req.assigned_agent_id,
            parent_task_id=req.parent_task_id,
            requires_approval_gate=req.requires_approval_gate,
            input_context_json=json.dumps(req.input_context),
            output_artifacts_json=json.dumps([]),
            created_at=now,
            updated_at=now,
        )

        async with self.session_factory() as session:
            async with session.begin():
                session.add(task_model)
                for dep_id in req.depends_on:
                    dep_edge = TaskDependencyModel(
                        task_id=req.task_id,
                        depends_on_task_id=dep_id,
                    )
                    session.add(dep_edge)
            await session.commit()

        return await self.get_by_id(req.task_id)  # type: ignore[return-value]

    async def get_by_id(self, task_id: str) -> TaskResponse | None:
        """Fetch a task along with its prerequisite dependencies and blocked downstream tasks."""
        async with self.session_factory() as session:
            model = await session.get(TaskModel, task_id)
            if not model:
                return None

            from sqlalchemy import select

            # Fetch dependencies (what this task depends on)
            dep_stmt = select(TaskDependencyModel.depends_on_task_id).where(
                TaskDependencyModel.task_id == task_id
            )
            dep_res = await session.execute(dep_stmt)
            depends_on = [row[0] for row in dep_res.fetchall()]

            # Fetch dependents (what tasks are blocked by this task)
            block_stmt = select(TaskDependencyModel.task_id).where(
                TaskDependencyModel.depends_on_task_id == task_id
            )
            block_res = await session.execute(block_stmt)
            blocks = [row[0] for row in block_res.fetchall()]

            return model.to_response(depends_on=depends_on, blocks=blocks)

    async def list_by_engagement(self, engagement_id: str) -> list[TaskResponse]:
        """List all tasks in an engagement graph with dependency references."""
        async with self.session_factory() as session:
            from sqlalchemy import select

            stmt = (
                select(TaskModel)
                .where(TaskModel.engagement_id == engagement_id)
                .order_by(TaskModel.priority.desc())
            )
            res = await session.execute(stmt)
            tasks = res.scalars().all()

            results: list[TaskResponse] = []
            for t in tasks:
                # Fetch dependencies
                dep_stmt = select(TaskDependencyModel.depends_on_task_id).where(
                    TaskDependencyModel.task_id == t.id
                )
                dep_res = await session.execute(dep_stmt)
                depends_on = [row[0] for row in dep_res.fetchall()]

                # Fetch blocks
                block_stmt = select(TaskDependencyModel.task_id).where(
                    TaskDependencyModel.depends_on_task_id == t.id
                )
                block_res = await session.execute(block_stmt)
                blocks = [row[0] for row in block_res.fetchall()]

                results.append(t.to_response(depends_on=depends_on, blocks=blocks))

            return results

    async def update_status(self, task_id: str, status: TaskStatus | str) -> TaskResponse | None:
        """Update task lifecycle status."""
        status_val = status.value if isinstance(status, TaskStatus) else status
        async with self.session_factory() as session:
            async with session.begin():
                model = await session.get(TaskModel, task_id)
                if not model:
                    return None
                model.status = status_val
                model.updated_at = datetime.now(UTC).isoformat()
            await session.commit()

        return await self.get_by_id(task_id)

    async def assign_agent(self, task_id: str, agent_id: str) -> TaskResponse | None:
        """Assign an active AI employee agent to a task."""
        async with self.session_factory() as session:
            async with session.begin():
                model = await session.get(TaskModel, task_id)
                if not model:
                    return None
                model.assigned_agent_id = agent_id
                model.status = TaskStatus.RUNNING.value
                model.updated_at = datetime.now(UTC).isoformat()
            await session.commit()

        return await self.get_by_id(task_id)
