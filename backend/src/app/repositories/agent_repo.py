"""Concrete AIEmployee (Agent) repository wrapping SQLAlchemy session."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.agent import (
    AgentCreateRequest,
    AgentResponse,
    AgentStatus,
    AIEmployeeModel,
)
from app.repositories.base import BaseRepository


class AgentRepository(BaseRepository[AIEmployeeModel, str]):
    """Typed repository for AIEmployee entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(AIEmployeeModel, session)

    async def create_agent(self, req: AgentCreateRequest) -> AgentResponse:
        now = datetime.now(UTC).isoformat()
        model = AIEmployeeModel(
            id=req.id,
            role_id=req.role_id,
            department_id=req.department_id,
            display_name=req.display_name,
            status=req.status.value,
            current_task_id=req.current_task_id,
            memory_ref=req.memory_ref,
            workspace_path=req.workspace_path,
            x_coord=req.x_coord,
            y_coord=req.y_coord,
            created_at=now,
            updated_at=now,
        )
        self.session.add(model)
        await self.session.flush()
        return model.to_response()

    async def get_agent_response(self, agent_id: str) -> AgentResponse | None:
        model = await self.get_by_id(agent_id)
        return model.to_response() if model else None

    async def list_agents(self) -> list[AgentResponse]:
        stmt = select(AIEmployeeModel).order_by(AIEmployeeModel.id)
        res = await self.session.execute(stmt)
        return [row.to_response() for row in res.scalars().all()]

    async def list_by_status(self, status: AgentStatus | str) -> list[AgentResponse]:
        status_val = status.value if isinstance(status, AgentStatus) else status
        stmt = (
            select(AIEmployeeModel)
            .where(AIEmployeeModel.status == status_val)
            .order_by(AIEmployeeModel.id)
        )
        res = await self.session.execute(stmt)
        return [row.to_response() for row in res.scalars().all()]

    async def list_by_department(self, department_id: str) -> list[AgentResponse]:
        stmt = (
            select(AIEmployeeModel)
            .where(AIEmployeeModel.department_id == department_id)
            .order_by(AIEmployeeModel.id)
        )
        res = await self.session.execute(stmt)
        return [row.to_response() for row in res.scalars().all()]

    async def update_status(
        self,
        agent_id: str,
        status: AgentStatus | str,
        current_task_id: str | None = None,
        clear_task_id: bool = False,
    ) -> AgentResponse | None:
        status_val = status.value if isinstance(status, AgentStatus) else status
        model = await self.get_by_id(agent_id)
        if not model:
            return None
        model.status = status_val
        if clear_task_id:
            model.current_task_id = None
        elif current_task_id is not None:
            model.current_task_id = current_task_id
        model.updated_at = datetime.now(UTC).isoformat()
        await self.session.flush()
        return model.to_response()
