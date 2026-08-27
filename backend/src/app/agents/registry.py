"""In-memory thread-safe Agent Registry tracking live execution handles distinct from DB state."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agents.state_machine import (
    AgentLifecycleState,
    AgentStateMachine,
)
from app.core.logging import get_logger
from app.domain.agent import AgentStatus
from app.domain.audit import AuditEventCreateRequest
from app.orchestrator.core import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork

logger = get_logger("agents.registry")

# Non-terminal active states that must be reconciled to RECOVERY on backend restart
NON_TERMINAL_STATES: set[str] = {
    AgentLifecycleState.PLANNING.value,
    AgentLifecycleState.ASSIGNED.value,
    AgentLifecycleState.PREPARING.value,
    AgentLifecycleState.RUNNING.value,
    AgentLifecycleState.WAITING_BLOCKED.value,
    AgentLifecycleState.COMMUNICATION.value,
    AgentLifecycleState.REVIEW.value,
    "executing",
    "awaiting_approval",
    "reporting",
}


class AgentRuntimeHandle(BaseModel):
    """Live in-memory orchestration handle for an active AI Employee."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    agent_id: str = Field(description="Unique identifier of the AI Employee")
    display_name: str = Field(default="")
    role_id: str = Field(default="")
    department_id: str = Field(default="")
    state_machine: AgentStateMachine = Field(description="Active FSM instance")
    current_task_id: str | None = Field(default=None)
    current_async_task: Any | None = Field(default=None, description="Active asyncio.Task handle")
    workspace_path: str | None = Field(default=None)
    memory_ref: str | None = Field(default=None)
    engagement_id: str | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)
    registered_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_heartbeat: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def current_state(self) -> AgentLifecycleState:
        """Return the current FSM lifecycle state of the agent."""
        return self.state_machine.current_state

    @property
    def is_busy(self) -> bool:
        """Determine if agent is actively executing or engaged in work."""
        return self.state_machine.current_state in (
            AgentLifecycleState.ASSIGNED,
            AgentLifecycleState.PREPARING,
            AgentLifecycleState.RUNNING,
            AgentLifecycleState.COMMUNICATION,
            AgentLifecycleState.REVIEW,
            AgentLifecycleState.RECOVERY,
        )

    def cancel_task(self, reason: str = "cancelled") -> bool:
        """Cancel the running background asyncio Task if currently active."""
        if self.current_async_task is not None and not self.current_async_task.done():
            self.current_async_task.cancel()
            logger.info(
                f"Cancelled active asyncio task for agent '{self.agent_id}' ({reason})",
                agent_id=self.agent_id,
                reason=reason,
            )
            return True
        return False


class AgentReconciliationReport(BaseModel):
    """Summary of state reconciliation performed during backend startup."""

    total_checked: int = 0
    reconciled_count: int = 0
    reconciled_agent_ids: list[str] = Field(default_factory=list)
    idle_agent_ids: list[str] = Field(default_factory=list)
    terminal_agent_ids: list[str] = Field(default_factory=list)
    details: list[dict[str, Any]] = Field(default_factory=list)
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class AgentRegistry:
    """Thread-safe in-memory runtime registry mapping agent_id to live orchestration handles."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentRuntimeHandle] = {}
        self._department_index: dict[str, set[str]] = {}
        self._role_index: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        agent_id: str,
        role_id: str,
        department_id: str,
        display_name: str = "",
        state_machine: AgentStateMachine | None = None,
        current_task_id: str | None = None,
        current_async_task: asyncio.Task[Any] | None = None,
        workspace_path: str | None = None,
        memory_ref: str | None = None,
        engagement_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentRuntimeHandle:
        """Register a live agent orchestration handle into memory."""
        async with self._lock:
            fsm = state_machine or AgentStateMachine(
                agent_id=agent_id, initial_state=AgentLifecycleState.IDLE
            )
            if current_task_id:
                fsm.current_task_id = current_task_id

            handle = AgentRuntimeHandle(
                agent_id=agent_id,
                display_name=display_name or agent_id,
                role_id=role_id,
                department_id=department_id,
                state_machine=fsm,
                current_task_id=current_task_id,
                current_async_task=current_async_task,
                workspace_path=workspace_path,
                memory_ref=memory_ref,
                engagement_id=engagement_id,
                metadata=metadata or {},
            )

            self._agents[agent_id] = handle

            # Maintain indexes
            if department_id not in self._department_index:
                self._department_index[department_id] = set()
            self._department_index[department_id].add(agent_id)

            if role_id not in self._role_index:
                self._role_index[role_id] = set()
            self._role_index[role_id].add(agent_id)

            logger.debug(
                "Registered live agent in runtime registry",
                agent_id=agent_id,
                role_id=role_id,
                department_id=department_id,
                state=handle.current_state.value,
            )
            return handle

    async def unregister(self, agent_id: str) -> AgentRuntimeHandle | None:
        """Unregister an agent from active memory and cancel its running background task."""
        async with self._lock:
            handle = self._agents.pop(agent_id, None)
            if not handle:
                return None

            handle.cancel_task("agent_unregistered")

            # Clean indexes
            if handle.department_id in self._department_index:
                self._department_index[handle.department_id].discard(agent_id)
                if not self._department_index[handle.department_id]:
                    del self._department_index[handle.department_id]

            if handle.role_id in self._role_index:
                self._role_index[handle.role_id].discard(agent_id)
                if not self._role_index[handle.role_id]:
                    del self._role_index[handle.role_id]

            logger.debug("Unregistered agent from runtime registry", agent_id=agent_id)
            return handle

    async def get(self, agent_id: str) -> AgentRuntimeHandle | None:
        """Look up live agent handle by agent_id."""
        async with self._lock:
            return self._agents.get(agent_id)

    async def has(self, agent_id: str) -> bool:
        """Check if an agent is currently registered in memory."""
        async with self._lock:
            return agent_id in self._agents

    async def list_active(self) -> list[AgentRuntimeHandle]:
        """List all active agent handles."""
        async with self._lock:
            return list(self._agents.values())

    async def list_by_department(self, department_id: str) -> list[AgentRuntimeHandle]:
        """List all agent handles belonging to a specific department."""
        async with self._lock:
            agent_ids = self._department_index.get(department_id, set())
            return [self._agents[aid] for aid in agent_ids if aid in self._agents]

    async def list_by_role(self, role_id: str) -> list[AgentRuntimeHandle]:
        """List all agent handles matching a specialist role."""
        async with self._lock:
            agent_ids = self._role_index.get(role_id, set())
            return [self._agents[aid] for aid in agent_ids if aid in self._agents]

    async def list_by_status(self, status: AgentLifecycleState | str) -> list[AgentRuntimeHandle]:
        """List all agent handles in a given lifecycle status."""
        status_val = (
            status.value if isinstance(status, AgentLifecycleState) else str(status).lower()
        )
        async with self._lock:
            return [h for h in self._agents.values() if h.current_state.value == status_val]

    async def count(self) -> int:
        """Return count of registered agents."""
        async with self._lock:
            return len(self._agents)

    async def update_task_handle(
        self,
        agent_id: str,
        task_id: str | None,
        async_task: asyncio.Task[Any] | None = None,
    ) -> AgentRuntimeHandle | None:
        """Update the active task pointer and asyncio background Task handle for an agent."""
        async with self._lock:
            handle = self._agents.get(agent_id)
            if not handle:
                return None

            handle.current_task_id = task_id
            handle.state_machine.current_task_id = task_id
            handle.current_async_task = async_task
            handle.last_heartbeat = datetime.now(UTC).isoformat()
            return handle

    async def cancel_agent(self, agent_id: str, reason: str = "operator_cancel") -> bool:
        """Cancel a specific agent's background task."""
        async with self._lock:
            handle = self._agents.get(agent_id)
            if handle:
                return handle.cancel_task(reason)
            return False

    async def cancel_all(self, reason: str = "backend_shutdown") -> int:
        """Cancel all running agent background tasks across the registry."""
        async with self._lock:
            cancelled = 0
            for handle in self._agents.values():
                if handle.cancel_task(reason):
                    cancelled += 1
            logger.info(f"Cancelled {cancelled} active agent background tasks ({reason})")
            return cancelled

    async def clear(self) -> None:
        """Clear the registry and cancel all running tasks (primarily for test resets)."""
        await self.cancel_all("registry_cleared")
        async with self._lock:
            self._agents.clear()
            self._department_index.clear()
            self._role_index.clear()

    async def reconcile_with_db(self, session_factory: Any) -> AgentReconciliationReport:
        """Reconcile in-memory agent registry with persistent database records on backend startup.

        Technical Decision: Any agent left in a non-terminal active DB state (RUNNING, PREPARING,
        PLANNING, WAITING_BLOCKED, etc.) after an unexpected crash or backend restart is reconciled
        to 'RECOVERY' state, not silently resumed.
        """
        report = AgentReconciliationReport()

        async with UnitOfWork(session_factory) as uow:
            db_agents = await uow.agents.list_all()

            for agent in db_agents:
                report.total_checked += 1
                status_raw = str(agent.status).lower()

                # 1. Non-terminal interrupted state -> Reconcile to RECOVERY
                if status_raw in NON_TERMINAL_STATES:
                    report.reconciled_count += 1
                    report.reconciled_agent_ids.append(agent.id)

                    # Update database status to RECOVERY
                    await uow.agents.update_status(
                        agent_id=agent.id,
                        status=AgentStatus.RECOVERY.value,
                        current_task_id=agent.current_task_id,
                    )

                    # Record audit event
                    corr_id = f"corr-reconcile-{agent.id}-{uuid.uuid4().hex[:8]}"
                    await uow.audit.append_audit_event(
                        AuditEventCreateRequest(
                            event_id=f"aud-rec-{agent.id}-{uuid.uuid4().hex[:8]}",
                            engagement_id="system-reconciliation",
                            correlation_id=corr_id,
                            event_type="agent_reconciled_after_restart",
                            actor_type="SYSTEM",
                            actor_id="agent-registry",
                            payload={
                                "agent_id": agent.id,
                                "prior_db_status": status_raw,
                                "reconciled_status": AgentLifecycleState.RECOVERY.value,
                                "interrupted_task_id": agent.current_task_id,
                                "reason": (
                                    f"Backend restart detected while agent '{agent.id}' was in '{status_raw}'. "
                                    "Reconciled to RECOVERY state for safe operator review / error recovery."
                                ),
                            },
                        )
                    )

                    # Initialize FSM in RECOVERY state
                    fsm = AgentStateMachine(
                        agent_id=agent.id,
                        initial_state=AgentLifecycleState.RECOVERY,
                    )
                    fsm.current_task_id = agent.current_task_id

                    # Register in runtime registry
                    await self.register(
                        agent_id=agent.id,
                        role_id=agent.role_id,
                        department_id=agent.department_id,
                        display_name=agent.display_name,
                        state_machine=fsm,
                        current_task_id=agent.current_task_id,
                        workspace_path=agent.workspace_path,
                        memory_ref=agent.memory_ref,
                        metadata={"reconciled_from": status_raw},
                    )

                    # Broadcast state changed event
                    await global_orchestrator.emit_event(
                        event_type="agent_state_changed",
                        correlation_id=corr_id,
                        agent_id=agent.id,
                        department_id=agent.department_id,
                        task_id=agent.current_task_id,
                        payload={
                            "agent_id": agent.id,
                            "prior_state": status_raw,
                            "new_state": AgentLifecycleState.RECOVERY.value,
                            "reason": "startup_reconciliation",
                            "correlation_id": corr_id,
                            "task_id": agent.current_task_id,
                            "department_id": agent.department_id,
                        },
                    )

                    report.details.append(
                        {
                            "agent_id": agent.id,
                            "action": "RECONCILED_TO_RECOVERY",
                            "prior_status": status_raw,
                            "task_id": agent.current_task_id,
                        }
                    )

                # 2. Idle agents -> Initialize in IDLE
                elif status_raw == AgentLifecycleState.IDLE.value:
                    report.idle_agent_ids.append(agent.id)
                    fsm = AgentStateMachine(
                        agent_id=agent.id,
                        initial_state=AgentLifecycleState.IDLE,
                    )
                    await self.register(
                        agent_id=agent.id,
                        role_id=agent.role_id,
                        department_id=agent.department_id,
                        display_name=agent.display_name,
                        state_machine=fsm,
                        workspace_path=agent.workspace_path,
                        memory_ref=agent.memory_ref,
                    )

                # 3. Terminal or already in recovery
                else:
                    report.terminal_agent_ids.append(agent.id)
                    try:
                        initial_state = AgentLifecycleState(status_raw)
                    except Exception:
                        initial_state = AgentLifecycleState.IDLE

                    fsm = AgentStateMachine(
                        agent_id=agent.id,
                        initial_state=initial_state,
                    )
                    fsm.current_task_id = agent.current_task_id
                    await self.register(
                        agent_id=agent.id,
                        role_id=agent.role_id,
                        department_id=agent.department_id,
                        display_name=agent.display_name,
                        state_machine=fsm,
                        current_task_id=agent.current_task_id,
                        workspace_path=agent.workspace_path,
                        memory_ref=agent.memory_ref,
                    )

            await uow.commit()

        logger.info(
            f"Agent reconciliation complete: {report.reconciled_count}/{report.total_checked} agents reconciled to RECOVERY",
            reconciled_count=report.reconciled_count,
            total_checked=report.total_checked,
        )
        return report


# Global singleton instance of the AgentRegistry
global_agent_registry = AgentRegistry()
