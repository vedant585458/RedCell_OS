"""AgentStateChanged event models, dispatchers, and transactional lifecycle synchronization."""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.agents.state_machine import (
    AgentLifecycleState,
    AgentStateMachine,
    StateTransitionRecord,
)
from app.core.logging import get_logger
from app.domain.audit import AuditEventCreateRequest
from app.orchestrator.core import global_orchestrator
from app.orchestrator.models import OrchestratorEvent
from app.repositories.unit_of_work import UnitOfWork

logger = get_logger("agents.events")


class AgentStateChangedEventPayload(BaseModel):
    """Structured payload emitted on every successful agent FSM transition."""

    agent_id: str = Field(description="Unique identifier of the AI Employee")
    prior_state: str = Field(description="Previous lifecycle state")
    new_state: str = Field(description="New/Current lifecycle state")
    reason: str = Field(default="", description="Trigger or reason for the transition")
    correlation_id: str = Field(
        description="Correlation ID linking transition to parent task/engagement"
    )
    engagement_id: str | None = Field(default=None)
    task_id: str | None = Field(default=None)
    department_id: str | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class AgentLifecycleService:
    """Service synchronizing FSM state transitions with database persistence and real-time event broadcasting."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory
        self._fsm_cache: dict[str, AgentStateMachine] = {}

    def get_or_create_fsm(
        self,
        agent_id: str,
        current_db_state: str = "idle",
    ) -> AgentStateMachine:
        """Get or initialize the in-memory state machine for an agent."""
        if agent_id not in self._fsm_cache:
            try:
                initial_state = AgentLifecycleState(current_db_state.lower())
            except Exception:
                initial_state = AgentLifecycleState.IDLE
            self._fsm_cache[agent_id] = AgentStateMachine(
                agent_id=agent_id, initial_state=initial_state
            )
        return self._fsm_cache[agent_id]

    async def transition_agent_state(
        self,
        agent_id: str,
        target_state: AgentLifecycleState,
        trigger: str = "",
        correlation_id: str = "",
        engagement_id: str | None = None,
        task_id: str | None = None,
        department_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[StateTransitionRecord, OrchestratorEvent]:
        """Execute a state transition, persist DB update, and broadcast AgentStateChanged event atomically.

        Guarantees 1:1 mapping: Exactly one event is emitted per successful transition.
        """
        async with UnitOfWork(self.session_factory) as uow:
            agent_model = await uow.agents.get_by_id(agent_id)
            if not agent_model:
                raise ValueError(f"AI Employee '{agent_id}' not found in database")

            fsm = self.get_or_create_fsm(agent_id, current_db_state=str(agent_model.status))

            # 1. Execute FSM transition (raises InvalidStateTransitionError if illegal)
            transition_record = fsm.transition_to(
                target_state=target_state,
                trigger=trigger,
                correlation_id=correlation_id,
                metadata=metadata,
            )

            # 2. Update relational database status and task pointer
            clear_task = target_state in (
                AgentLifecycleState.IDLE,
                AgentLifecycleState.COMPLETED,
                AgentLifecycleState.TERMINATION,
            )
            await uow.agents.update_status(
                agent_id=agent_id,
                status=target_state.value,
                current_task_id=task_id if not clear_task else None,
                clear_task_id=clear_task,
            )

            # 3. Record audit trail entry
            event_payload = AgentStateChangedEventPayload(
                agent_id=agent_id,
                prior_state=transition_record.from_state.value,
                new_state=transition_record.to_state.value,
                reason=trigger,
                correlation_id=correlation_id or f"corr-fsm-{agent_id}",
                engagement_id=engagement_id or agent_model.department_id,
                task_id=task_id,
                department_id=department_id or agent_model.department_id,
                metadata=metadata or {},
            )

            if engagement_id:
                await uow.audit.append_audit_event(
                    AuditEventCreateRequest(
                        event_id=f"aud-fsm-{agent_id}-{uuid.uuid4().hex[:8]}",
                        engagement_id=engagement_id,
                        correlation_id=correlation_id or f"corr-fsm-{agent_id}",
                        event_type="agent_state_changed",
                        actor_type="AGENT",
                        actor_id=agent_id,
                        payload=event_payload.model_dump(),
                    )
                )

            await uow.commit()

        # 4. Emit event to orchestrator event bus (broadcasts to WebSocket clients)
        orchestrator_event = await global_orchestrator.emit_event(
            event_type="agent_state_changed",
            correlation_id=correlation_id or f"corr-fsm-{agent_id}",
            engagement_id=engagement_id,
            agent_id=agent_id,
            department_id=department_id,
            task_id=task_id,
            payload=event_payload.model_dump(),
        )

        logger.info(
            f"Agent '{agent_id}' transitioned {transition_record.from_state} -> {transition_record.to_state} ({trigger})",
            agent_id=agent_id,
            from_state=transition_record.from_state,
            to_state=transition_record.to_state,
            trigger=trigger,
        )

        return transition_record, orchestrator_event
