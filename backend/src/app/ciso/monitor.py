"""Event-driven CISO progress monitoring loop evaluating task completions, failures, and replanning."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.domain.audit import AuditEventCreateRequest
from app.domain.task import TaskStatus
from app.llm.interface import AgentBrain
from app.orchestrator.core import global_orchestrator
from app.orchestrator.models import OrchestratorEvent
from app.repositories.unit_of_work import UnitOfWork

logger = get_logger("ciso.monitor")

MAX_REPLANS_PER_ENGAGEMENT = 3


class CisoDecisionType(StrEnum):
    """Categorical decisions produced by the CISO intelligence monitoring loop."""

    CONTINUE = "CONTINUE"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"
    REPLAN = "REPLAN"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"
    COMPLETE_ENGAGEMENT = "COMPLETE_ENGAGEMENT"
    EMERGENCY_HALT = "EMERGENCY_HALT"


class CisoDecision(BaseModel):
    """Decision object emitted by the CISO Progress Monitor."""

    decision_id: str = Field(default_factory=lambda: f"dec-{uuid.uuid4().hex[:8]}")
    engagement_id: str
    triggered_by_event: str = Field(description="Event type triggering the monitor evaluation")
    decision_type: CisoDecisionType
    reason: str = Field(description="Strategic justification for the decision")
    replan_count: int = Field(default=0)
    unblocked_task_ids: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class CisoProgressMonitor:
    """Event-driven CISO supervisor monitoring task progress, handling DAG unblocking, and orchestrating replanning."""

    def __init__(self, session_factory: Any, brain: AgentBrain | None = None) -> None:
        self.session_factory = session_factory
        self.brain = brain
        self._replan_counters: dict[str, int] = {}

    async def handle_event(self, event: OrchestratorEvent) -> CisoDecision | None:
        """Process an orchestrator event and determine next strategic action."""
        if not event.engagement_id:
            return None

        engagement_id = event.engagement_id

        if event.event_type == "task_completed":
            return await self._on_task_completed(engagement_id, event)
        elif event.event_type == "task_failed":
            return await self._on_task_failed(engagement_id, event)
        elif event.event_type == "finding_recorded":
            return await self._on_finding_recorded(engagement_id, event)

        return None

    async def _on_task_completed(
        self, engagement_id: str, event: OrchestratorEvent
    ) -> CisoDecision:
        """Evaluate DAG state on task completion: advance downstream tasks or complete engagement."""
        unblocked_tasks: list[str] = []

        async with UnitOfWork(self.session_factory) as uow:
            tasks = await uow.tasks.list_by_engagement(engagement_id)
            completed_task_ids = {t.task_id for t in tasks if t.status == TaskStatus.COMPLETED}

            # Check if all tasks are completed
            all_done = len(tasks) > 0 and len(completed_task_ids) == len(tasks)
            if all_done:
                await uow.engagements.update_status(engagement_id, "COMPLETED")
                decision = CisoDecision(
                    engagement_id=engagement_id,
                    triggered_by_event="task_completed",
                    decision_type=CisoDecisionType.COMPLETE_ENGAGEMENT,
                    reason="All planned tasks in the engagement DAG have completed successfully.",
                    actions=["finalize_report", "prepare_client_deliverables"],
                )
            else:
                # Find pending tasks whose prerequisites are now completely satisfied
                for t in tasks:
                    if t.status == TaskStatus.PENDING:
                        prereqs_satisfied = all(dep in completed_task_ids for dep in t.depends_on)
                        if prereqs_satisfied:
                            await uow.tasks.update_status(t.task_id, TaskStatus.READY)
                            unblocked_tasks.append(t.task_id)

                decision = CisoDecision(
                    engagement_id=engagement_id,
                    triggered_by_event="task_completed",
                    decision_type=CisoDecisionType.CONTINUE,
                    reason=f"Task '{event.task_id}' finished. Unblocked {len(unblocked_tasks)} downstream tasks.",
                    unblocked_task_ids=unblocked_tasks,
                    actions=["dispatch_ready_tasks"]
                    if unblocked_tasks
                    else ["await_running_tasks"],
                )

            # Record decision in immutable audit log
            await uow.audit.append_audit_event(
                AuditEventCreateRequest(
                    event_id=f"aud-dec-{decision.decision_id}",
                    engagement_id=engagement_id,
                    correlation_id=event.correlation_id,
                    event_type="ciso_decision_made",
                    actor_type="AGENT",
                    actor_id="agent-ciso-01",
                    payload=decision.model_dump(),
                )
            )
            await uow.commit()

        # Emit decision event to orchestrator event bus
        await self._emit_decision_event(decision, event.correlation_id)
        return decision

    async def _on_task_failed(self, engagement_id: str, event: OrchestratorEvent) -> CisoDecision:
        """Handle task execution failure with bounded replanning or human escalation."""
        current_replans = self._replan_counters.get(engagement_id, 0)
        failed_task_id = event.task_id or "unknown_task"

        async with UnitOfWork(self.session_factory) as uow:
            # Check stability limit to prevent infinite replanning loops
            if current_replans >= MAX_REPLANS_PER_ENGAGEMENT:
                decision = CisoDecision(
                    engagement_id=engagement_id,
                    triggered_by_event="task_failed",
                    decision_type=CisoDecisionType.ESCALATE_TO_HUMAN,
                    reason=(
                        f"Task '{failed_task_id}' failed and engagement has reached the maximum replanning limit "
                        f"({MAX_REPLANS_PER_ENGAGEMENT} attempts). Escalating to human operator."
                    ),
                    replan_count=current_replans,
                    actions=["prompt_operator_intervention", "freeze_dependent_tasks"],
                )
            else:
                self._replan_counters[engagement_id] = current_replans + 1
                decision = CisoDecision(
                    engagement_id=engagement_id,
                    triggered_by_event="task_failed",
                    decision_type=CisoDecisionType.REPLAN,
                    reason=(
                        f"Task '{failed_task_id}' failed execution. Initiating tactical replan "
                        f"(Attempt {current_replans + 1}/{MAX_REPLANS_PER_ENGAGEMENT})."
                    ),
                    replan_count=current_replans + 1,
                    actions=["trigger_ciso_replanning_pipeline", "reschedule_task"],
                )

            # Record in immutable audit log
            await uow.audit.append_audit_event(
                AuditEventCreateRequest(
                    event_id=f"aud-dec-{decision.decision_id}",
                    engagement_id=engagement_id,
                    correlation_id=event.correlation_id,
                    event_type="ciso_decision_made",
                    actor_type="AGENT",
                    actor_id="agent-ciso-01",
                    payload=decision.model_dump(),
                )
            )
            await uow.commit()

        await self._emit_decision_event(decision, event.correlation_id)
        return decision

    async def _on_finding_recorded(
        self, engagement_id: str, event: OrchestratorEvent
    ) -> CisoDecision:
        """Evaluate high-risk findings for immediate operator notification or approval requirements."""
        payload = event.payload or {}
        severity = str(payload.get("severity", "MEDIUM"))

        decision_type = (
            CisoDecisionType.REQUEST_APPROVAL
            if severity in ("CRITICAL", "HIGH")
            else CisoDecisionType.CONTINUE
        )

        decision = CisoDecision(
            engagement_id=engagement_id,
            triggered_by_event="finding_recorded",
            decision_type=decision_type,
            reason=f"Recorded {severity} severity finding: '{payload.get('title', 'Vulnerability')}'.",
            actions=["prompt_approval_gate"]
            if decision_type == CisoDecisionType.REQUEST_APPROVAL
            else ["continue_scan"],
        )

        await self._emit_decision_event(decision, event.correlation_id)
        return decision

    async def _emit_decision_event(self, decision: CisoDecision, correlation_id: str) -> None:
        """Broadcast CISODecision event to the orchestrator event stream."""
        logger.info(
            f"CISO Decision: {decision.decision_type} - {decision.reason}",
            engagement_id=decision.engagement_id,
            decision_type=decision.decision_type,
        )
        await global_orchestrator.emit_event(
            event_type="ciso_decision_made",
            correlation_id=correlation_id,
            engagement_id=decision.engagement_id,
            agent_id="agent-ciso-01",
            payload=decision.model_dump(),
        )
