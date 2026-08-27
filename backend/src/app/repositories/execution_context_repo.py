"""Concrete ExecutionContext repository wrapping SQLAlchemy session."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.execution_context import (
    ExecutionContextArchive,
    ExecutionContextModel,
)
from app.repositories.base import BaseRepository


class ExecutionContextRepository(BaseRepository[ExecutionContextModel, str]):
    """Typed repository handling persistence and audit queries for archived execution contexts."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ExecutionContextModel, session)

    async def save_archive(self, archive: ExecutionContextArchive) -> ExecutionContextArchive:
        """Persist an archived execution context record."""
        model = ExecutionContextModel(
            id=archive.context_id,
            task_id=archive.task_id,
            agent_id=archive.agent_id,
            role_id=archive.role_id,
            engagement_id=archive.engagement_id,
            department_id=archive.department_id,
            final_status=archive.final_status,
            archive_payload_json=archive.model_dump_json(),
            created_at=archive.created_at,
            closed_at=archive.closed_at,
        )
        self.session.add(model)
        await self.session.flush()
        return archive

    async def get_by_task_id(self, task_id: str) -> ExecutionContextArchive | None:
        """Fetch archived context for a specific task."""
        stmt = select(ExecutionContextModel).where(ExecutionContextModel.task_id == task_id)
        res = await self.session.execute(stmt)
        model = res.scalar_one_or_none()
        return model.to_archive() if model else None

    async def list_by_engagement(self, engagement_id: str) -> list[ExecutionContextArchive]:
        """List all archived execution contexts for an engagement."""
        stmt = (
            select(ExecutionContextModel)
            .where(ExecutionContextModel.engagement_id == engagement_id)
            .order_by(ExecutionContextModel.created_at.desc())
        )
        res = await self.session.execute(stmt)
        return [row.to_archive() for row in res.scalars().all()]
