"""Department capacity evaluation and bounded auto-staffing service."""

import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.domain.agent import AgentCreateRequest, AgentResponse, AgentStatus
from app.domain.task import TaskStatus
from app.orchestrator.core import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork

logger = get_logger("services.staffing")

DEFAULT_MAX_AGENTS_PER_DEPARTMENT = 8


class DepartmentLoadState(StrEnum):
    """Capacity load classification for a department."""

    UNDERUTILIZED = "UNDERUTILIZED"
    OPTIMAL = "OPTIMAL"
    AT_CAPACITY = "AT_CAPACITY"
    OVERLOADED = "OVERLOADED"


class DepartmentCapacityStatus(BaseModel):
    """Capacity and workload metrics for a department."""

    department_id: str
    department_name: str
    total_agents: int
    idle_agents: int
    busy_agents: int
    ready_tasks: int
    pending_tasks: int
    unassigned_ready_tasks: int
    capacity_deficit: int = Field(
        description="Number of ready tasks lacking available agent workers"
    )
    max_department_capacity: int
    can_hire_more: bool
    utilization_rate: float = Field(ge=0.0, le=1.0, description="Fraction of agents currently busy")
    load_state: DepartmentLoadState


class StaffingRecommendation(BaseModel):
    """Staffing proposal indicating needed specialist roles and hire counts."""

    department_id: str
    role_id: str
    hire_count: int
    reason: str
    capped_by_max_limit: bool = False


class DepartmentStaffingService:
    """Service computing department workload capacity and executing bounded agent hiring."""

    def __init__(
        self,
        session_factory: Any,
        max_agents_per_department: int = DEFAULT_MAX_AGENTS_PER_DEPARTMENT,
    ) -> None:
        self.session_factory = session_factory
        self.max_agents_per_department = max_agents_per_department

    async def evaluate_department_capacity(
        self,
        department_id: str,
        engagement_id: str | None = None,
    ) -> DepartmentCapacityStatus:
        """Compute real-time workload capacity and agent availability for a department."""
        async with UnitOfWork(self.session_factory) as uow:
            dept = await uow.departments.get_by_id(department_id)
            if not dept:
                raise ValueError(f"Department '{department_id}' not found")

            agents = await uow.agents.list_by_department(department_id)
            total_agents = len(agents)
            idle_agents = sum(1 for a in agents if a.status == AgentStatus.IDLE)
            busy_agents = total_agents - idle_agents

            task_counts = await uow.tasks.get_department_task_counts(
                department_id=department_id,
                engagement_id=engagement_id,
            )
            ready_tasks = task_counts.get("ready", 0)
            pending_tasks = task_counts.get("pending", 0)

            # Query unassigned ready tasks
            ready_task_items = await uow.tasks.list_by_department(
                department_id=department_id,
                engagement_id=engagement_id,
                status=TaskStatus.READY,
            )
            unassigned_ready = sum(1 for t in ready_task_items if not t.assigned_agent_id)

            # Capacity deficit is unassigned ready tasks exceeding available idle workers
            capacity_deficit = max(0, unassigned_ready - idle_agents)
            can_hire = total_agents < self.max_agents_per_department

            utilization = (busy_agents / total_agents) if total_agents > 0 else 1.0

            if capacity_deficit > 0:
                load_state = DepartmentLoadState.OVERLOADED
            elif total_agents >= self.max_agents_per_department and idle_agents == 0:
                load_state = DepartmentLoadState.AT_CAPACITY
            elif idle_agents > 0 and (ready_tasks + pending_tasks) == 0:
                load_state = DepartmentLoadState.UNDERUTILIZED
            else:
                load_state = DepartmentLoadState.OPTIMAL

            return DepartmentCapacityStatus(
                department_id=dept.id,
                department_name=dept.name,
                total_agents=total_agents,
                idle_agents=idle_agents,
                busy_agents=busy_agents,
                ready_tasks=ready_tasks,
                pending_tasks=pending_tasks,
                unassigned_ready_tasks=unassigned_ready,
                capacity_deficit=capacity_deficit,
                max_department_capacity=self.max_agents_per_department,
                can_hire_more=can_hire,
                utilization_rate=round(utilization, 2),
                load_state=load_state,
            )

    async def evaluate_staffing_needs(
        self,
        department_id: str,
        engagement_id: str | None = None,
    ) -> list[StaffingRecommendation]:
        """Determine specific specialist roles requiring additional agent hires."""
        capacity = await self.evaluate_department_capacity(department_id, engagement_id)
        if capacity.capacity_deficit == 0 or not capacity.can_hire_more:
            return []

        async with UnitOfWork(self.session_factory) as uow:
            unassigned_tasks = await uow.tasks.list_by_department(
                department_id=department_id,
                engagement_id=engagement_id,
                status=TaskStatus.READY,
            )

        # Count needed roles
        role_needs: dict[str, int] = {}
        for t in unassigned_tasks:
            if not t.assigned_agent_id:
                role_needs[t.assigned_role] = role_needs.get(t.assigned_role, 0) + 1

        recommendations: list[StaffingRecommendation] = []
        available_headcount = self.max_agents_per_department - capacity.total_agents

        for role_id, needed in role_needs.items():
            if available_headcount <= 0:
                break

            hires_to_grant = min(needed, available_headcount)
            is_capped = needed > available_headcount
            available_headcount -= hires_to_grant

            recommendations.append(
                StaffingRecommendation(
                    department_id=department_id,
                    role_id=role_id,
                    hire_count=hires_to_grant,
                    reason=f"Department has {needed} ready tasks requiring specialist role '{role_id}'.",
                    capped_by_max_limit=is_capped,
                )
            )

        return recommendations

    async def auto_staff_department(
        self,
        department_id: str,
        engagement_id: str | None = None,
    ) -> list[AgentResponse]:
        """Execute bounded auto-hiring for an overloaded department and assign new agents to ready tasks."""
        recommendations = await self.evaluate_staffing_needs(department_id, engagement_id)
        if not recommendations:
            return []

        newly_hired_agents: list[AgentResponse] = []

        async with UnitOfWork(self.session_factory) as uow:
            unassigned_tasks = await uow.tasks.list_by_department(
                department_id=department_id,
                engagement_id=engagement_id,
                status=TaskStatus.READY,
            )

            for rec in recommendations:
                for _ in range(rec.hire_count):
                    role_slug = rec.role_id.replace("role_", "").replace("_", "-")
                    agent_id = f"agent-{role_slug}-{uuid.uuid4().hex[:4]}"
                    display_name = (
                        f"{rec.role_id.replace('role_', '').replace('_', ' ').title()} Agent"
                    )

                    created_agent = await uow.agents.create_agent(
                        AgentCreateRequest(
                            id=agent_id,
                            role_id=rec.role_id,
                            department_id=rec.department_id,
                            display_name=display_name,
                            status=AgentStatus.IDLE,
                            workspace_path=f"/data/workspaces/{agent_id}",
                            x_coord=300,
                            y_coord=200,
                        )
                    )
                    newly_hired_agents.append(created_agent)

                    # Assign agent to the first matching unassigned ready task
                    for t in unassigned_tasks:
                        if t.assigned_role == rec.role_id and not t.assigned_agent_id:
                            await uow.tasks.assign_agent(t.task_id, created_agent.id)
                            t.assigned_agent_id = created_agent.id
                            break

            await uow.commit()

        # Broadcast agent_hired events
        for agent in newly_hired_agents:
            logger.info(
                f"Auto-hired AI Employee: {agent.display_name} ({agent.id}) in {department_id}",
                agent_id=agent.id,
                department_id=department_id,
            )
            await global_orchestrator.emit_event(
                event_type="agent_hired",
                correlation_id=f"corr-staff-{agent.id}",
                agent_id=agent.id,
                department_id=department_id,
                payload=agent.model_dump(),
            )

        return newly_hired_agents

    async def evaluate_all_departments(
        self,
        engagement_id: str | None = None,
    ) -> list[DepartmentCapacityStatus]:
        """Compute workload capacity across all 7 canonical departments."""
        async with UnitOfWork(self.session_factory) as uow:
            depts = await uow.departments.list_departments()

        statuses: list[DepartmentCapacityStatus] = []
        for d in depts:
            status = await self.evaluate_department_capacity(d.id, engagement_id)
            statuses.append(status)

        return statuses
