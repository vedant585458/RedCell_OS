"""AIEmployee (Agent) domain model, Pydantic schemas, and SQLAlchemy ORM entity."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.engagement import Base


class AgentStatus(StrEnum):
    """Finite-State Machine (FSM) status enum for AI Employees."""

    IDLE = "IDLE"
    PLANNING = "PLANNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    REPORTING = "REPORTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EMERGENCY_HALTED = "EMERGENCY_HALTED"


class AgentCreateRequest(BaseModel):
    """Payload to spawn or register a new AI employee."""

    id: str = Field(
        ...,
        min_length=2,
        max_length=64,
        description="Unique agent identifier (e.g. agent-recon-01)",
    )
    role_id: str = Field(..., description="Referenced specialist role ID (e.g. role_web_discovery)")
    department_id: str = Field(..., description="Referenced department ID (e.g. dept_recon)")
    display_name: str = Field(..., min_length=2, max_length=128)
    status: AgentStatus = Field(default=AgentStatus.IDLE)
    current_task_id: str | None = Field(default=None)
    memory_ref: str | None = Field(
        default=None, description="Path or reference to agent memory store"
    )
    workspace_path: str | None = Field(
        default=None, description="Path to isolated workspace scratchpad"
    )
    x_coord: int = Field(default=100, description="2D Office X coordinate")
    y_coord: int = Field(default=100, description="2D Office Y coordinate")


class AgentUpdateRequest(BaseModel):
    """Payload to update an AI employee's runtime status or assigned task."""

    status: AgentStatus | None = None
    current_task_id: str | None = None
    memory_ref: str | None = None
    workspace_path: str | None = None
    x_coord: int | None = None
    y_coord: int | None = None


class AgentResponse(BaseModel):
    """Outbound API response representing an AI Employee entity."""

    id: str
    role_id: str
    department_id: str
    display_name: str
    status: AgentStatus
    current_task_id: str | None
    memory_ref: str | None
    workspace_path: str | None
    x_coord: int
    y_coord: int
    created_at: str
    updated_at: str


class AIEmployeeModel(Base):
    """SQLAlchemy relational table mapping for AI Employees (Agents)."""

    __tablename__ = "ai_employees"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    role_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("roles.id"), nullable=False, index=True
    )
    department_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("departments.id"), nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=AgentStatus.IDLE.value, index=True
    )
    current_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    memory_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    workspace_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    x_coord: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    y_coord: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)

    def to_response(self) -> AgentResponse:
        """Convert ORM model to validated Pydantic AgentResponse."""
        return AgentResponse(
            id=str(self.id),
            role_id=str(self.role_id),
            department_id=str(self.department_id),
            display_name=str(self.display_name),
            status=AgentStatus(str(self.status)),
            current_task_id=str(self.current_task_id) if self.current_task_id else None,
            memory_ref=str(self.memory_ref) if self.memory_ref else None,
            workspace_path=str(self.workspace_path) if self.workspace_path else None,
            x_coord=int(self.x_coord),
            y_coord=int(self.y_coord),
            created_at=str(self.created_at),
            updated_at=str(self.updated_at),
        )


class AIEmployeeRepository:
    """Repository handling CRUD and state-machine transitions for AI Employees."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    async def create(self, req: AgentCreateRequest) -> AgentResponse:
        """Create and persist a new AI Employee entity."""
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

        async with self.session_factory() as session:
            async with session.begin():
                session.add(model)
            await session.commit()
            return model.to_response()

    async def get_by_id(self, agent_id: str) -> AgentResponse | None:
        """Fetch an AI Employee by ID."""
        async with self.session_factory() as session:
            model = await session.get(AIEmployeeModel, agent_id)
            if model:
                return model.to_response()
            return None

    async def list_all(self) -> list[AgentResponse]:
        """List all registered AI Employees."""
        async with self.session_factory() as session:
            from sqlalchemy import select

            stmt = select(AIEmployeeModel).order_by(AIEmployeeModel.id)
            result = await session.execute(stmt)
            return [row.to_response() for row in result.scalars()]

    async def list_by_status(self, status: AgentStatus | str) -> list[AgentResponse]:
        """Query AI Employees filtered by explicit status enum."""
        status_val = status.value if isinstance(status, AgentStatus) else status
        async with self.session_factory() as session:
            from sqlalchemy import select

            stmt = (
                select(AIEmployeeModel)
                .where(AIEmployeeModel.status == status_val)
                .order_by(AIEmployeeModel.id)
            )
            result = await session.execute(stmt)
            return [row.to_response() for row in result.scalars()]

    async def list_by_department(self, department_id: str) -> list[AgentResponse]:
        """Query AI Employees belonging to a specific department."""
        async with self.session_factory() as session:
            from sqlalchemy import select

            stmt = (
                select(AIEmployeeModel)
                .where(AIEmployeeModel.department_id == department_id)
                .order_by(AIEmployeeModel.id)
            )
            result = await session.execute(stmt)
            return [row.to_response() for row in result.scalars()]

    async def update_status(
        self,
        agent_id: str,
        status: AgentStatus | str,
        current_task_id: str | None = None,
    ) -> AgentResponse | None:
        """Update the FSM state of an agent."""
        status_val = status.value if isinstance(status, AgentStatus) else status
        async with self.session_factory() as session:
            async with session.begin():
                model = await session.get(AIEmployeeModel, agent_id)
                if not model:
                    return None
                model.status = status_val
                if current_task_id is not None:
                    model.current_task_id = current_task_id
                model.updated_at = datetime.now(UTC).isoformat()
            await session.commit()
            return model.to_response()

    async def update_position(self, agent_id: str, x: int, y: int) -> AgentResponse | None:
        """Update 2D office simulation coordinates for an agent."""
        async with self.session_factory() as session:
            async with session.begin():
                model = await session.get(AIEmployeeModel, agent_id)
                if not model:
                    return None
                model.x_coord = x
                model.y_coord = y
                model.updated_at = datetime.now(UTC).isoformat()
            await session.commit()
            return model.to_response()
