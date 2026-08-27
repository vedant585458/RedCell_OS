"""Concrete Task and TaskDependency repository wrapping SQLAlchemy session."""

import json
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.task import (
    TaskCreateRequest,
    TaskDependencyModel,
    TaskModel,
    TaskResponse,
    TaskStatus,
)
from app.repositories.base import BaseRepository


class TaskRepository(BaseRepository[TaskModel, str]):
    """Typed repository for Task and dependency graph edge operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(TaskModel, session)

    async def create_task(self, req: TaskCreateRequest) -> TaskResponse:
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
        self.session.add(task_model)

        for dep_id in req.depends_on:
            dep_edge = TaskDependencyModel(
                task_id=req.task_id,
                depends_on_task_id=dep_id,
            )
            self.session.add(dep_edge)

        await self.session.flush()
        return await self.get_task_response(req.task_id)  # type: ignore[return-value]

    async def get_task_response(self, task_id: str) -> TaskResponse | None:
        model = await self.get_by_id(task_id)
        if not model:
            return None

        # Fetch dependencies
        dep_stmt = select(TaskDependencyModel.depends_on_task_id).where(
            TaskDependencyModel.task_id == task_id
        )
        dep_res = await self.session.execute(dep_stmt)
        depends_on = [row[0] for row in dep_res.fetchall()]

        # Fetch blocks
        block_stmt = select(TaskDependencyModel.task_id).where(
            TaskDependencyModel.depends_on_task_id == task_id
        )
        block_res = await self.session.execute(block_stmt)
        blocks = [row[0] for row in block_res.fetchall()]

        return model.to_response(depends_on=depends_on, blocks=blocks)

    async def list_by_engagement(self, engagement_id: str) -> list[TaskResponse]:
        stmt = (
            select(TaskModel)
            .where(TaskModel.engagement_id == engagement_id)
            .order_by(TaskModel.priority.desc())
        )
        res = await self.session.execute(stmt)
        tasks = res.scalars().all()

        results: list[TaskResponse] = []
        for t in tasks:
            dep_stmt = select(TaskDependencyModel.depends_on_task_id).where(
                TaskDependencyModel.task_id == t.id
            )
            dep_res = await self.session.execute(dep_stmt)
            depends_on = [row[0] for row in dep_res.fetchall()]

            block_stmt = select(TaskDependencyModel.task_id).where(
                TaskDependencyModel.depends_on_task_id == t.id
            )
            block_res = await self.session.execute(block_stmt)
            blocks = [row[0] for row in block_res.fetchall()]

            results.append(t.to_response(depends_on=depends_on, blocks=blocks))

        return results

    async def list_by_department(
        self,
        department_id: str,
        engagement_id: str | None = None,
        status: TaskStatus | str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskResponse]:
        """List tasks scoped to a department with optional engagement and status filters."""
        return await self.list_tasks(
            department_id=department_id,
            engagement_id=engagement_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def list_tasks(
        self,
        department_id: str | None = None,
        status: TaskStatus | str | None = None,
        assigned_agent_id: str | None = None,
        engagement_id: str | None = None,
        priority: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskResponse]:
        """List tasks with dynamic filtering across department, status, agent, engagement, and priority."""
        stmt = select(TaskModel)
        if department_id:
            stmt = stmt.where(TaskModel.department_id == department_id)
        if engagement_id:
            stmt = stmt.where(TaskModel.engagement_id == engagement_id)
        if assigned_agent_id:
            stmt = stmt.where(TaskModel.assigned_agent_id == assigned_agent_id)
        if priority is not None:
            stmt = stmt.where(TaskModel.priority == priority)
        if status:
            status_val = status.value if isinstance(status, TaskStatus) else str(status)
            stmt = stmt.where(func.lower(TaskModel.status) == status_val.lower())

        stmt = (
            stmt.order_by(TaskModel.priority.desc(), TaskModel.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        res = await self.session.execute(stmt)
        tasks = res.scalars().all()

        results: list[TaskResponse] = []
        for t in tasks:
            dep_stmt = select(TaskDependencyModel.depends_on_task_id).where(
                TaskDependencyModel.task_id == t.id
            )
            dep_res = await self.session.execute(dep_stmt)
            depends_on = [row[0] for row in dep_res.fetchall()]

            block_stmt = select(TaskDependencyModel.task_id).where(
                TaskDependencyModel.depends_on_task_id == t.id
            )
            block_res = await self.session.execute(block_stmt)
            blocks = [row[0] for row in block_res.fetchall()]

            results.append(t.to_response(depends_on=depends_on, blocks=blocks))

        return results

    async def get_department_task_counts(
        self,
        department_id: str,
        engagement_id: str | None = None,
    ) -> dict[str, int]:
        """Compute task status aggregation counts via SQL GROUP BY for scale and performance."""
        stmt = select(TaskModel.status, func.count(TaskModel.id)).where(
            TaskModel.department_id == department_id
        )
        if engagement_id:
            stmt = stmt.where(TaskModel.engagement_id == engagement_id)
        stmt = stmt.group_by(TaskModel.status)

        res = await self.session.execute(stmt)
        raw_counts: dict[str, int] = {str(row[0]): int(row[1]) for row in res.fetchall()}

        counts = {
            "pending": raw_counts.get(TaskStatus.PENDING.value, 0),
            "ready": raw_counts.get(TaskStatus.READY.value, 0),
            "in_progress": raw_counts.get(TaskStatus.RUNNING.value, 0),
            "awaiting_approval": raw_counts.get(TaskStatus.AWAITING_APPROVAL.value, 0),
            "completed": raw_counts.get(TaskStatus.COMPLETED.value, 0),
            "failed": raw_counts.get(TaskStatus.FAILED.value, 0),
            "blocked": raw_counts.get(TaskStatus.BLOCKED.value, 0),
            "total": sum(raw_counts.values()),
        }
        return counts

    async def update_status(self, task_id: str, status: TaskStatus | str) -> TaskResponse | None:
        status_val = status.value if isinstance(status, TaskStatus) else status
        model = await self.get_by_id(task_id)
        if not model:
            return None
        model.status = status_val
        model.updated_at = datetime.now(UTC).isoformat()
        await self.session.flush()
        return await self.get_task_response(task_id)

    async def update_task(
        self,
        task_id: str,
        status: TaskStatus | str | None = None,
        assigned_agent_id: str | None = None,
        clear_assigned_agent: bool = False,
    ) -> TaskResponse | None:
        model = await self.get_by_id(task_id)
        if not model:
            return None
        if status is not None:
            status_val = status.value if isinstance(status, TaskStatus) else str(status)
            model.status = status_val
        if clear_assigned_agent:
            model.assigned_agent_id = None
        elif assigned_agent_id is not None:
            model.assigned_agent_id = assigned_agent_id
        model.updated_at = datetime.now(UTC).isoformat()
        await self.session.flush()
        return await self.get_task_response(task_id)

    async def assign_agent(self, task_id: str, agent_id: str) -> TaskResponse | None:
        model = await self.get_by_id(task_id)
        if not model:
            return None
        model.assigned_agent_id = agent_id
        model.status = TaskStatus.RUNNING.value
        model.updated_at = datetime.now(UTC).isoformat()
        await self.session.flush()
        return await self.get_task_response(task_id)
