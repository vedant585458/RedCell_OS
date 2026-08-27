"""Event-driven Task Readiness Listener auto-transitioning dependent tasks to READY on TaskCompleted events."""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.domain.audit import AuditEventCreateRequest
from app.domain.task import TaskResponse, TaskStatus
from app.orchestrator.core import global_orchestrator
from app.orchestrator.models import OrchestratorEvent
from app.repositories.unit_of_work import UnitOfWork
from app.tasks.dependency_graph import TaskDependencyGraphEngine

logger = get_logger("tasks.readiness_listener")


class TaskReadyEventPayload(BaseModel):
    """Structured payload emitted when a task becomes READY for execution / scheduling."""

    task_id: str
    engagement_id: str
    department_id: str
    assigned_role: str
    priority: int
    unblocked_by_task_id: str
    correlation_id: str
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class TaskReadinessListener:
    """Event-driven listener reacting to TaskCompleted events and advancing satisfied downstream tasks from PENDING to READY."""

    def __init__(
        self,
        session_factory: Any,
        graph_engine: TaskDependencyGraphEngine | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.graph_engine = graph_engine or TaskDependencyGraphEngine(session_factory)
        self._is_listening: bool = False

    @property
    def is_listening(self) -> bool:
        return self._is_listening

    def start_listening(self) -> None:
        """Register the event subscriber on the central orchestrator event bus."""
        if not self._is_listening:
            global_orchestrator.register_event_subscriber(self.handle_event)
            self._is_listening = True
            logger.info("TaskReadinessListener active and listening for task_completed events")

    def stop_listening(self) -> None:
        """Unregister the event subscriber from the central orchestrator event bus."""
        if self._is_listening:
            global_orchestrator.unregister_event_subscriber(self.handle_event)
            self._is_listening = False
            logger.info("TaskReadinessListener stopped")

    async def handle_event(self, event: OrchestratorEvent) -> None:
        """Process incoming orchestrator events, triggering dependency graph evaluation on task completions."""
        is_completed_event = event.event_type == "task_completed" or (
            event.event_type == "task_status_changed"
            and str(event.payload.get("new_status", "")).upper() == TaskStatus.COMPLETED.value
        )

        if not is_completed_event:
            return

        task_id = event.task_id or str(event.payload.get("task_id", ""))
        engagement_id = event.engagement_id or str(event.payload.get("engagement_id", ""))

        if not task_id or not engagement_id:
            logger.debug(
                "Skipping task completion event missing task_id or engagement_id",
                event_type=event.event_type,
            )
            return

        await self.process_task_completion(
            completed_task_id=task_id,
            engagement_id=engagement_id,
            correlation_id=event.correlation_id,
        )

    async def process_task_completion(
        self,
        completed_task_id: str,
        engagement_id: str,
        correlation_id: str = "",
    ) -> list[TaskResponse]:
        """Evaluate DAG dependencies, flip newly satisfied tasks from PENDING to READY in DB,

        and emit TaskReady events for scheduler consumption (P19).
        """
        corr_id = correlation_id or f"corr-readiness-{completed_task_id}-{uuid.uuid4().hex[:8]}"

        # 1. Load engagement graph and compute newly unblocked tasks
        graph = await self.graph_engine.load_engagement_graph(engagement_id)
        unblocked_task_ids = graph.compute_unblocked_tasks(completed_task_id)

        if not unblocked_task_ids:
            logger.debug(
                f"Task '{completed_task_id}' completed; no downstream tasks unblocked",
                completed_task_id=completed_task_id,
            )
            return []

        unblocked_responses: list[TaskResponse] = []

        # 2. Transactionally update task statuses and record audit logs
        async with UnitOfWork(self.session_factory) as uow:
            for tid in unblocked_task_ids:
                # Update status in relational database to READY
                await uow.tasks.update_status(tid, TaskStatus.READY)
                task_resp = await uow.tasks.get_task_response(tid)
                if not task_resp:
                    continue

                unblocked_responses.append(task_resp)

                # Record immutable audit event
                await uow.audit.append_audit_event(
                    AuditEventCreateRequest(
                        event_id=f"aud-ready-{tid[:8]}-{uuid.uuid4().hex[:6]}",
                        engagement_id=engagement_id,
                        correlation_id=corr_id,
                        event_type="task_ready",
                        actor_type="SYSTEM",
                        actor_id="task_readiness_listener",
                        payload={
                            "task_id": tid,
                            "unblocked_by": completed_task_id,
                            "department_id": task_resp.department_id,
                            "assigned_role": task_resp.assigned_role,
                            "priority": task_resp.priority,
                        },
                    )
                )

            await uow.commit()

        # 3. Broadcast TaskReady and TaskStatusChanged events over orchestrator bus
        for task_resp in unblocked_responses:
            ready_payload = TaskReadyEventPayload(
                task_id=task_resp.task_id,
                engagement_id=engagement_id,
                department_id=task_resp.department_id,
                assigned_role=task_resp.assigned_role,
                priority=task_resp.priority,
                unblocked_by_task_id=completed_task_id,
                correlation_id=corr_id,
            )

            # Primary TaskReady event for scheduler (Phase P19)
            await global_orchestrator.emit_event(
                event_type="task_ready",
                correlation_id=corr_id,
                engagement_id=engagement_id,
                department_id=task_resp.department_id,
                task_id=task_resp.task_id,
                payload=ready_payload.model_dump(),
            )

            # Standard status change event for UI / real-time visualization
            await global_orchestrator.emit_event(
                event_type="task_status_changed",
                correlation_id=corr_id,
                engagement_id=engagement_id,
                department_id=task_resp.department_id,
                task_id=task_resp.task_id,
                payload={
                    "task_id": task_resp.task_id,
                    "prior_status": TaskStatus.PENDING.value,
                    "new_status": TaskStatus.READY.value,
                    "reason": f"Prerequisite task '{completed_task_id}' completed; all dependencies satisfied",
                },
            )

        logger.info(
            f"Task '{completed_task_id}' completion unblocked {len(unblocked_responses)} tasks to READY: "
            f"{[t.task_id for t in unblocked_responses]}",
            completed_task_id=completed_task_id,
            unblocked_count=len(unblocked_responses),
        )

        return unblocked_responses


# Global singleton instance of the listener
global_readiness_listener = TaskReadinessListener(None)  # Session factory set on startup
