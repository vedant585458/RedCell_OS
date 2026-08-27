"""Concrete Execution repository wrapping SQLAlchemy session."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.execution import (
    ExecutionCreateRequest,
    ExecutionModel,
    ExecutionResponse,
)
from app.repositories.base import BaseRepository


class ExecutionRepository(BaseRepository[ExecutionModel, str]):
    """Typed repository for Process Execution telemetry entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ExecutionModel, session)

    async def record_execution(self, req: ExecutionCreateRequest) -> ExecutionResponse:
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
        self.session.add(model)
        await self.session.flush()
        return model.to_response()

    async def list_by_task(self, task_id: str) -> list[ExecutionResponse]:
        stmt = (
            select(ExecutionModel)
            .where(ExecutionModel.task_id == task_id)
            .order_by(ExecutionModel.started_at.asc())
        )
        res = await self.session.execute(stmt)
        return [row.to_response() for row in res.scalars()]
