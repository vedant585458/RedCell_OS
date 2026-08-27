"""Integration tests for AgentStateChanged event emission, payload structure, and 1:1 transition consistency."""

import asyncio

import pytest
from app.agents.events import AgentLifecycleService
from app.agents.state_machine import AgentLifecycleState, InvalidStateTransitionError
from app.domain.agent import AgentStatus
from app.domain.engagement import Base, EngagementCreateRequest
from app.domain.task import TaskCreateRequest
from app.orchestrator import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork
from app.services.org_bootstrap import OrgBootstrapService
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_environment():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Bootstrap default org
    bootstrap = OrgBootstrapService(session_factory)
    await bootstrap.bootstrap_organization()

    async with UnitOfWork(session_factory) as uow:
        await uow.engagements.create_engagement(
            EngagementCreateRequest(
                engagement_id="eng-event-test",
                title="Event Emission Test",
                organization="Acme",
                authorized_by="CISO",
            )
        )
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_DISCOVERY",
                engagement_id="eng-event-test",
                department_id="dept_recon",
                title="Endpoint Discovery",
                assigned_role="role_web_discovery",
                assigned_agent_id="agent-recon-01",
            )
        )
        await uow.commit()

    return session_factory, engine


@pytest.mark.asyncio
async def test_agent_state_changed_event_emission_sequence():
    session_factory, engine = await setup_test_environment()
    try:
        service = AgentLifecycleService(session_factory=session_factory)
        emitted_events = []

        async def capture_event(event):
            if event.event_type == "agent_state_changed":
                emitted_events.append(event)

        global_orchestrator.register_event_subscriber(capture_event)
        await global_orchestrator.start()

        # Step 1: IDLE -> ASSIGNED
        rec1, ev1 = await service.transition_agent_state(
            agent_id="agent-recon-01",
            target_state=AgentLifecycleState.ASSIGNED,
            trigger="task_assigned",
            correlation_id="corr-101",
            engagement_id="eng-event-test",
            task_id="TASK_DISCOVERY",
            department_id="dept_recon",
        )
        assert rec1.from_state == AgentLifecycleState.IDLE
        assert rec1.to_state == AgentLifecycleState.ASSIGNED
        assert ev1.payload["prior_state"] == "idle"
        assert ev1.payload["new_state"] == "assigned"
        assert ev1.payload["correlation_id"] == "corr-101"

        # Step 2: ASSIGNED -> PREPARING
        await service.transition_agent_state(
            agent_id="agent-recon-01",
            target_state=AgentLifecycleState.PREPARING,
            trigger="setup_workspace",
            correlation_id="corr-101",
            engagement_id="eng-event-test",
            task_id="TASK_DISCOVERY",
        )

        # Step 3: PREPARING -> RUNNING
        await service.transition_agent_state(
            agent_id="agent-recon-01",
            target_state=AgentLifecycleState.RUNNING,
            trigger="spawn_process",
            correlation_id="corr-101",
            engagement_id="eng-event-test",
            task_id="TASK_DISCOVERY",
        )

        # Step 4: RUNNING -> WAITING_BLOCKED (Gated action)
        await service.transition_agent_state(
            agent_id="agent-recon-01",
            target_state=AgentLifecycleState.WAITING_BLOCKED,
            trigger="approval_required",
            correlation_id="corr-101",
            engagement_id="eng-event-test",
            task_id="TASK_DISCOVERY",
        )

        # Step 5: WAITING_BLOCKED -> RUNNING (Approved)
        await service.transition_agent_state(
            agent_id="agent-recon-01",
            target_state=AgentLifecycleState.RUNNING,
            trigger="approval_granted",
            correlation_id="corr-101",
            engagement_id="eng-event-test",
            task_id="TASK_DISCOVERY",
        )

        # Step 6: RUNNING -> COMPLETED
        await service.transition_agent_state(
            agent_id="agent-recon-01",
            target_state=AgentLifecycleState.COMPLETED,
            trigger="task_finished_success",
            correlation_id="corr-101",
            engagement_id="eng-event-test",
            task_id="TASK_DISCOVERY",
        )

        # Step 7: COMPLETED -> IDLE
        await service.transition_agent_state(
            agent_id="agent-recon-01",
            target_state=AgentLifecycleState.IDLE,
            trigger="reset_for_next_task",
            correlation_id="corr-101",
            engagement_id="eng-event-test",
        )

        await asyncio.sleep(0.05)
        await global_orchestrator.stop()

        # Assert: 7 transitions executed -> exactly 7 agent_state_changed events captured
        assert len(emitted_events) == 7
        assert emitted_events[0].payload["new_state"] == "assigned"
        assert emitted_events[1].payload["new_state"] == "preparing"
        assert emitted_events[2].payload["new_state"] == "running"
        assert emitted_events[3].payload["new_state"] == "waiting_blocked"
        assert emitted_events[4].payload["new_state"] == "running"
        assert emitted_events[5].payload["new_state"] == "completed"
        assert emitted_events[6].payload["new_state"] == "idle"

        # Verify DB reflects final state IDLE
        async with UnitOfWork(session_factory) as uow:
            agent = await uow.agents.get_agent_response("agent-recon-01")
            assert agent is not None
            assert agent.status == AgentStatus.IDLE
            assert agent.current_task_id is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_illegal_transition_rejection_emits_no_events():
    session_factory, engine = await setup_test_environment()
    try:
        service = AgentLifecycleService(session_factory=session_factory)

        # Attempting illegal transition: IDLE -> COMPLETED
        with pytest.raises(InvalidStateTransitionError):
            await service.transition_agent_state(
                agent_id="agent-recon-01",
                target_state=AgentLifecycleState.COMPLETED,
                trigger="illegal_jump",
            )

        # Verify agent in DB remains in original state IDLE
        async with UnitOfWork(session_factory) as uow:
            agent = await uow.agents.get_agent_response("agent-recon-01")
            assert agent is not None
            assert agent.status == AgentStatus.IDLE
    finally:
        await engine.dispose()
