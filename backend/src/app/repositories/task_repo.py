"""Concrete Task and TaskDependency repository wrapping SQLAlchemy session."""

import json
from datetime import UTC, datetime

from sqlalchemy import select
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

    async def update_status(self, task_id: str, status: TaskStatus | str) -> TaskResponse | None:
        status_val = status.value if isinstance(status, TaskStatus) else status
        model = await self.get_by_id(task_id)
        if not model:
            return None
        model.status = status_val
        model.updated_at = datetime.now(UTC).isoformat()
        await self.session.flush()
        return await self.get_task_response(task_id)
