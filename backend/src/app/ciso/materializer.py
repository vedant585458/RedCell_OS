"""CISO Plan-to-Task Materialization Service converting validated strategic plans into persisted Task DAGs and AI Employees."""

import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.ciso.planner import CisoStrategicPlan
from app.core.logging import get_logger
from app.domain.agent import AgentCreateRequest, AgentStatus
from app.domain.audit import AuditEventCreateRequest
from app.domain.task import TaskCreateRequest, TaskResponse, TaskStatus
from app.orchestrator.core import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork

logger = get_logger("ciso.materializer")


class MaterializationResult(BaseModel):
    """Result summary returned after materializing a CISO plan into database rows."""

    engagement_id: str
    tasks_created: int = Field(description="Total tasks persisted in the database")
    dependencies_created: int = Field(description="Total dependency graph edges persisted")
    agents_hired: int = Field(description="New AI employees spawned for unstaffed roles")
    task_ids: list[str] = Field(description="List of all materialized task IDs")
    materialized_tasks: list[TaskResponse] = Field(
        description="Complete materialized task response objects"
    )


class PlanMaterializer:
    """Service converting validated CISO strategic plans into transactional Task DAGs and AIEmployee assignments."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    async def materialize_plan(self, plan: CisoStrategicPlan) -> MaterializationResult:
        """Transactionally persist all tasks, dependency edges, and dynamic agent hirings for a strategic plan.

        All-or-nothing guarantee: Full plan commits atomically via UnitOfWork or rolls back completely on failure.
        """
        logger.info(
            "Materializing strategic plan into execution DAG...",
            engagement_id=plan.engagement_id,
            total_tasks=plan.total_tasks,
        )

        materialized_tasks: list[TaskResponse] = []
        task_ids: list[str] = []
        dependencies_count = 0
        agents_hired_count = 0

        # Events to broadcast after successful DB commit
        post_commit_events: list[dict[str, Any]] = []

        async with UnitOfWork(self.session_factory) as uow:
            # Step 1: Ensure AI Employees exist for every required role in the plan
            role_to_agent_map: dict[str, str] = {}

            # Query existing agents
            existing_agents = await uow.agents.list_agents()
            for agent in existing_agents:
                if agent.role_id not in role_to_agent_map:
                    role_to_agent_map[agent.role_id] = agent.id

            # Check each planned task and hire new agents if role is unstaffed
            for task in plan.tasks:
                if task.assigned_role not in role_to_agent_map:
                    # Dynamically hire a new AI employee for this specialist role
                    role_slug = task.assigned_role.replace("role_", "").replace("_", "-")
                    new_agent_id = f"agent-{role_slug}-{uuid.uuid4().hex[:4]}"
                    agent_display_name = (
                        f"{task.assigned_role.replace('role_', '').replace('_', ' ').title()} Agent"
                    )

                    await uow.agents.create_agent(
                        AgentCreateRequest(
                            id=new_agent_id,
                            role_id=task.assigned_role,
                            department_id=task.department_id,
                            display_name=agent_display_name,
                            status=AgentStatus.IDLE,
                            workspace_path=f"/data/workspaces/{new_agent_id}",
                            x_coord=300,
                            y_coord=200,
                        )
                    )
                    role_to_agent_map[task.assigned_role] = new_agent_id
                    agents_hired_count += 1

                    post_commit_events.append(
                        {
                            "event_type": "agent_hired",
                            "agent_id": new_agent_id,
                            "department_id": task.department_id,
                            "payload": {
                                "agent_id": new_agent_id,
                                "role_id": task.assigned_role,
                                "department_id": task.department_id,
                                "display_name": agent_display_name,
                            },
                        }
                    )

            # Step 2: Persist all tasks and dependency edges
            for task in plan.tasks:
                assigned_agent = role_to_agent_map.get(task.assigned_role)
                initial_status = (
                    TaskStatus.READY if len(task.depends_on_task_ids) == 0 else TaskStatus.PENDING
                )

                create_task_req = TaskCreateRequest(
                    task_id=task.task_id,
                    engagement_id=plan.engagement_id,
                    department_id=task.department_id,
                    title=task.title,
                    description=f"Success Criteria: {task.success_criteria}",
                    priority=task.priority,
                    assigned_role=task.assigned_role,
                    assigned_agent_id=assigned_agent,
                    depends_on=task.depends_on_task_ids,
                    requires_approval_gate=task.requires_approval_gate,
                    input_context=task.input_context,
                )

                created_task = await uow.tasks.create_task(create_task_req)
                if initial_status == TaskStatus.READY:
                    await uow.tasks.update_status(task.task_id, TaskStatus.READY)
                    created_task.status = TaskStatus.READY

                materialized_tasks.append(created_task)
                task_ids.append(task.task_id)
                dependencies_count += len(task.depends_on_task_ids)

                post_commit_events.append(
                    {
                        "event_type": "task_created",
                        "task_id": task.task_id,
                        "agent_id": assigned_agent,
                        "department_id": task.department_id,
                        "payload": created_task.model_dump(),
                    }
                )

            # Step 3: Update Engagement status to ACTIVE
            await uow.engagements.update_status(plan.engagement_id, "ACTIVE")

            # Step 4: Record audit log entry
            await uow.audit.append_audit_event(
                AuditEventCreateRequest(
                    event_id=f"aud-plan-{plan.engagement_id}",
                    engagement_id=plan.engagement_id,
                    correlation_id=f"corr-{plan.engagement_id}",
                    event_type="plan_materialized",
                    actor_type="AGENT",
                    actor_id="agent-ciso-01",
                    payload={
                        "mission_title": plan.mission_title,
                        "tasks_count": len(materialized_tasks),
                        "dependencies_count": dependencies_count,
                        "agents_hired_count": agents_hired_count,
                        "task_ids": task_ids,
                    },
                )
            )

            # Commit the entire plan atomically
            await uow.commit()

        # Step 5: Broadcast real-time events to orchestrator bus after successful commit
        for event_item in post_commit_events:
            await global_orchestrator.emit_event(
                event_type=event_item["event_type"],
                correlation_id=f"corr-{plan.engagement_id}",
                engagement_id=plan.engagement_id,
                agent_id=event_item.get("agent_id"),
                department_id=event_item.get("department_id"),
                task_id=event_item.get("task_id"),
                payload=event_item["payload"],
            )

        logger.info(
            "Strategic plan successfully materialized",
            engagement_id=plan.engagement_id,
            tasks=len(materialized_tasks),
            dependencies=dependencies_count,
            agents_hired=agents_hired_count,
        )

        return MaterializationResult(
            engagement_id=plan.engagement_id,
            tasks_created=len(materialized_tasks),
            dependencies_created=dependencies_count,
            agents_hired=agents_hired_count,
            task_ids=task_ids,
            materialized_tasks=materialized_tasks,
        )
