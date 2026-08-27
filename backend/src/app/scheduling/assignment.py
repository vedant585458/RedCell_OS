"""Agent-Task Matching and Assignment Service with LRU idle agent selection, staffing fallback, and atomic state updates."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.events import AgentLifecycleService
from app.agents.registry import AgentRegistry, global_agent_registry
from app.agents.state_machine import AgentLifecycleState
from app.capabilities.registry import CapabilityRegistry, global_capability_registry
from app.core.logging import get_logger
from app.domain.agent import AgentStatus, AIEmployeeModel
from app.domain.audit import AuditEventCreateRequest
from app.domain.task import TaskStatus
from app.orchestrator.core import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork
from app.scheduling.scheduler import ScheduledTaskItem
from app.services.staffing import DepartmentStaffingService

logger = get_logger("scheduling.assignment")


class AssignmentError(Exception):
    """Base exception for task assignment errors."""

    pass


class TaskAssignedEventPayload(BaseModel):
    """Structured payload emitted when a task is successfully assigned to an AI employee."""

    task_id: str
    engagement_id: str
    department_id: str
    assigned_agent_id: str
    assigned_role: str
    priority: int
    correlation_id: str
    hired_new_agent: bool = False
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class AssignmentResult(BaseModel):
    """Result of an agent-task assignment attempt."""

    success: bool
    task_id: str
    assigned_agent_id: str | None = None
    assigned_role: str | None = None
    department_id: str | None = None
    hired_new_agent: bool = False
    reason: str = ""
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class AssignmentService:
    """Service matching scheduled tasks to available idle specialist agents or auto-hiring on capacity deficits."""

    def __init__(
        self,
        session_factory: Any,
        staffing_service: DepartmentStaffingService | None = None,
        capability_registry: CapabilityRegistry | None = None,
        agent_registry: AgentRegistry | None = None,
        lifecycle_service: AgentLifecycleService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.staffing_service = staffing_service or DepartmentStaffingService(session_factory)
        self.capability_registry = capability_registry or global_capability_registry
        self.agent_registry = agent_registry or global_agent_registry
        self.lifecycle_service = lifecycle_service or AgentLifecycleService(session_factory)
        self._assignment_lock = asyncio.Lock()

    async def assign_scheduled_item(
        self,
        item: ScheduledTaskItem,
        correlation_id: str = "",
    ) -> AssignmentResult:
        """Assign a ScheduledTaskItem dequeued from the PriorityScheduler to the best available agent."""
        return await self.assign_task(
            task_id=item.task_id,
            correlation_id=correlation_id,
        )

    async def find_best_idle_agent(
        self,
        department_id: str,
        required_role: str,
        uow: UnitOfWork,
    ) -> AIEmployeeModel | None:
        """Matching Algorithm: Filter idle agents by required department and role, selecting the Least-Recently-Used (LRU).

        LRU is determined by earliest `updated_at` timestamp to distribute work evenly across specialists.
        """
        assert uow.session is not None

        # Query idle agents in the specified department with matching role
        stmt = (
            select(AIEmployeeModel)
            .where(
                AIEmployeeModel.department_id == department_id,
                AIEmployeeModel.role_id == required_role,
                AIEmployeeModel.status == AgentStatus.IDLE.value,
            )
            .order_by(AIEmployeeModel.updated_at.asc())  # LRU: oldest updated_at first
        )
        res = await uow.session.execute(stmt)
        return res.scalars().first()

    async def assign_task(
        self,
        task_id: str,
        correlation_id: str = "",
    ) -> AssignmentResult:
        """Match and assign a task to the best available idle agent.

        Technical Decision: Assignment is transactional — task status, agent status, FSM transitions,
        and audit logging are committed atomically to prevent concurrent double-booking race conditions.
        """
        corr_id = correlation_id or f"corr-assign-{task_id}-{uuid.uuid4().hex[:8]}"

        # Concurrency Protection: Lock assignment evaluation globally
        async with self._assignment_lock:
            async with UnitOfWork(self.session_factory) as uow:
                # 1. Fetch task
                task_model = await uow.tasks.get_by_id(task_id)
                if not task_model:
                    return AssignmentResult(
                        success=False,
                        task_id=task_id,
                        reason=f"Task '{task_id}' not found in database.",
                    )

                dept_id = task_model.department_id
                required_role = task_model.assigned_role
                engagement_id = task_model.engagement_id
                priority = task_model.priority

                # 2. Find best idle agent using LRU matching
                agent_model = await self.find_best_idle_agent(
                    department_id=dept_id,
                    required_role=required_role,
                    uow=uow,
                )

                hired_new_agent = False

                # 3. Fallback to Staffing Service (P12) if no matching idle agent is available
                if not agent_model:
                    logger.info(
                        f"No idle agent with role '{required_role}' in '{dept_id}'. Triggering auto-staffing fallback.",
                        department_id=dept_id,
                        role_id=required_role,
                    )
                    # Attempt auto-hiring
                    hired_agents = await self.staffing_service.auto_staff_department(
                        department_id=dept_id,
                        engagement_id=engagement_id,
                    )
                    # Find newly hired agent matching required role
                    matching_hired = next(
                        (a for a in hired_agents if a.role_id == required_role), None
                    )
                    if matching_hired:
                        agent_model = await uow.agents.get_by_id(matching_hired.id)
                        hired_new_agent = True

                if not agent_model:
                    return AssignmentResult(
                        success=False,
                        task_id=task_id,
                        department_id=dept_id,
                        assigned_role=required_role,
                        reason=(
                            f"No idle agent available for role '{required_role}' in department '{dept_id}', "
                            "and department has reached maximum staffing capacity."
                        ),
                    )

                assigned_agent_id = agent_model.id

                # 4. Atomic Transactional Update: Update Agent and Task status
                # Update agent to ASSIGNED
                agent_model.status = AgentStatus.ASSIGNED.value
                agent_model.current_task_id = task_id
                agent_model.updated_at = datetime.now(UTC).isoformat()

                # Update task to ASSIGNED / RUNNING
                task_model.assigned_agent_id = assigned_agent_id
                task_model.status = TaskStatus.RUNNING.value
                task_model.updated_at = datetime.now(UTC).isoformat()

                # 5. Record immutable audit event
                await uow.audit.append_audit_event(
                    AuditEventCreateRequest(
                        event_id=f"aud-assign-{task_id[:8]}-{assigned_agent_id[:8]}",
                        engagement_id=engagement_id,
                        correlation_id=corr_id,
                        event_type="task_assigned",
                        actor_type="SYSTEM",
                        actor_id="assignment_service",
                        payload={
                            "task_id": task_id,
                            "agent_id": assigned_agent_id,
                            "role_id": required_role,
                            "department_id": dept_id,
                            "priority": priority,
                            "hired_new_agent": hired_new_agent,
                        },
                    )
                )

                await uow.commit()

            # 6. Update in-memory AgentRegistry & FSM state
            runtime_handle = await self.agent_registry.get(assigned_agent_id)
            if runtime_handle:
                await self.agent_registry.update_task_handle(
                    agent_id=assigned_agent_id,
                    task_id=task_id,
                )
                if runtime_handle.state_machine.can_transition_to(AgentLifecycleState.ASSIGNED):
                    runtime_handle.state_machine.transition_to(
                        AgentLifecycleState.ASSIGNED,
                        trigger="task_assigned_by_scheduler",
                        correlation_id=corr_id,
                        metadata={"task_id": task_id},
                    )

            # 7. Broadcast TaskAssigned and AgentStateChanged events
            assigned_payload = TaskAssignedEventPayload(
                task_id=task_id,
                engagement_id=engagement_id,
                department_id=dept_id,
                assigned_agent_id=assigned_agent_id,
                assigned_role=required_role,
                priority=priority,
                correlation_id=corr_id,
                hired_new_agent=hired_new_agent,
            )

            await global_orchestrator.emit_event(
                event_type="task_assigned",
                correlation_id=corr_id,
                engagement_id=engagement_id,
                department_id=dept_id,
                agent_id=assigned_agent_id,
                task_id=task_id,
                payload=assigned_payload.model_dump(),
            )

            await global_orchestrator.emit_event(
                event_type="agent_state_changed",
                correlation_id=corr_id,
                engagement_id=engagement_id,
                department_id=dept_id,
                agent_id=assigned_agent_id,
                task_id=task_id,
                payload={
                    "agent_id": assigned_agent_id,
                    "prior_state": "idle",
                    "new_state": "assigned",
                    "reason": "task_assigned",
                    "correlation_id": corr_id,
                    "task_id": task_id,
                    "department_id": dept_id,
                },
            )

            logger.info(
                f"Successfully assigned task '{task_id}' to agent '{assigned_agent_id}' ({required_role})",
                task_id=task_id,
                agent_id=assigned_agent_id,
                role=required_role,
                hired=hired_new_agent,
            )

            return AssignmentResult(
                success=True,
                task_id=task_id,
                assigned_agent_id=assigned_agent_id,
                assigned_role=required_role,
                department_id=dept_id,
                hired_new_agent=hired_new_agent,
                reason="Matched to idle specialist agent.",
            )


# Global singleton instance of the assignment service
global_assignment_service = AssignmentService(None)  # Session factory bound at runtime
