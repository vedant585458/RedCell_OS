"""Unit and integration tests for in-memory AgentRegistry and startup DB state reconciliation."""

import asyncio

import pytest
from app.agents.registry import AgentRegistry
from app.agents.state_machine import AgentLifecycleState, AgentStateMachine
from app.domain.agent import AgentCreateRequest, AgentStatus
from app.domain.engagement import Base, EngagementCreateRequest
from app.domain.task import TaskCreateRequest
from app.repositories.unit_of_work import UnitOfWork
from app.services.org_bootstrap import OrgBootstrapService
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_environment():
    """Create in-memory SQLite database, tables, and seeded organization for registry tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    bootstrap = OrgBootstrapService(session_factory)
    await bootstrap.bootstrap_organization()

    async with UnitOfWork(session_factory) as uow:
        await uow.engagements.create_engagement(
            EngagementCreateRequest(
                engagement_id="eng-reg-test",
                title="Registry Test Engagement",
                organization="CyberCorp",
                authorized_by="CISO",
            )
        )
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_WEB_RECON",
                engagement_id="eng-reg-test",
                department_id="dept_recon",
                title="Subdomain Enumeration",
                assigned_role="role_web_discovery",
                assigned_agent_id="agent-recon-01",
            )
        )
        await uow.commit()

    return session_factory, engine


@pytest.mark.asyncio
async def test_agent_registry_crud_and_lookups():
    """Verify in-memory registration, indexing by department/role, and retrieval operations."""
    registry = AgentRegistry()

    fsm = AgentStateMachine(
        agent_id="agent-test-01", initial_state=AgentLifecycleState.IDLE
    )
    handle = await registry.register(
        agent_id="agent-test-01",
        role_id="role_web_discovery",
        department_id="dept_recon",
        display_name="Recon Specialist 1",
        state_machine=fsm,
        workspace_path="/tmp/workspaces/agent-test-01",
    )

    assert handle.agent_id == "agent-test-01"
    assert handle.current_state == AgentLifecycleState.IDLE
    assert not handle.is_busy

    # Lookups
    assert await registry.has("agent-test-01") is True
    assert await registry.has("agent-nonexistent") is False

    retrieved = await registry.get("agent-test-01")
    assert retrieved is not None
    assert retrieved.display_name == "Recon Specialist 1"

    # Index lookups
    dept_agents = await registry.list_by_department("dept_recon")
    assert len(dept_agents) == 1
    assert dept_agents[0].agent_id == "agent-test-01"

    role_agents = await registry.list_by_role("role_web_discovery")
    assert len(role_agents) == 1
    assert role_agents[0].agent_id == "agent-test-01"

    # Unregister
    removed = await registry.unregister("agent-test-01")
    assert removed is not None
    assert await registry.has("agent-test-01") is False
    assert len(await registry.list_active()) == 0


@pytest.mark.asyncio
async def test_agent_registry_asyncio_task_tracking_and_cancellation():
    """Verify live background asyncio Tasks are tracked and can be cancelled individually or globally."""
    registry = AgentRegistry()

    task_ran = False
    task_cancelled = False

    async def long_running_probe():
        nonlocal task_ran, task_cancelled
        task_ran = True
        try:
            await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            task_cancelled = True
            raise

    # Spawn background task
    bg_task = asyncio.create_task(long_running_probe())

    fsm = AgentStateMachine(
        agent_id="agent-runner-01", initial_state=AgentLifecycleState.RUNNING
    )
    handle = await registry.register(
        agent_id="agent-runner-01",
        role_id="role_vulnerability_scanner",
        department_id="dept_vuln_assessment",
        state_machine=fsm,
        current_task_id="TASK_SCAN_01",
        current_async_task=bg_task,
    )

    assert handle.is_busy is True
    await asyncio.sleep(0.01)
    assert task_ran is True

    # Cancel via registry
    cancelled = await registry.cancel_agent("agent-runner-01", reason="operator_kill")
    assert cancelled is True

    await asyncio.sleep(0.01)
    assert bg_task.done() is True
    assert task_cancelled is True


@pytest.mark.asyncio
async def test_startup_reconciliation_reconciles_mid_task_agents_to_recovery():
    """Acceptance Criteria & Technical Decision: On backend restart, any agent left in a

    non-terminal DB state is reconciled to 'RECOVERY' state, not silently resumed.
    """
    session_factory, engine = await setup_test_environment()
    try:
        # Simulate mid-task states in the database before backend restart
        async with UnitOfWork(session_factory) as uow:
            # 1. agent-recon-01 was RUNNING with a task
            await uow.agents.update_status(
                agent_id="agent-recon-01",
                status=AgentStatus.RUNNING.value,
                current_task_id="TASK_WEB_RECON",
            )
            # 2. agent-vuln-01 was in PLANNING
            await uow.agents.update_status(
                agent_id="agent-vuln-01",
                status=AgentStatus.PLANNING.value,
                current_task_id="TASK_VULN_01",
            )
            # 3. agent-report-01 was in PREPARING
            await uow.agents.update_status(
                agent_id="agent-report-01",
                status=AgentStatus.PREPARING.value,
            )
            # 4. agent-sentinel-01 was IDLE (should remain IDLE)
            await uow.agents.update_status(
                agent_id="agent-sentinel-01",
                status=AgentStatus.IDLE.value,
            )
            # 5. agent-ciso-01 was IDLE (should remain IDLE)
            await uow.agents.update_status(
                agent_id="agent-ciso-01",
                status=AgentStatus.IDLE.value,
            )
            await uow.commit()

        # Simulate backend startup reconciliation
        registry = AgentRegistry()
        report = await registry.reconcile_with_db(session_factory)

        # Assert reconciliation counts
        assert report.total_checked == 5
        assert report.reconciled_count == 3
        assert "agent-recon-01" in report.reconciled_agent_ids
        assert "agent-vuln-01" in report.reconciled_agent_ids
        assert "agent-report-01" in report.reconciled_agent_ids
        assert "agent-sentinel-01" in report.idle_agent_ids
        assert "agent-ciso-01" in report.idle_agent_ids

        # Assert Database state: mid-task agents transitioned to RECOVERY
        async with UnitOfWork(session_factory) as uow:
            recon_agent = await uow.agents.get_by_id("agent-recon-01")
            assert recon_agent is not None
            assert recon_agent.status.upper() == AgentStatus.RECOVERY.value
            assert recon_agent.current_task_id == "TASK_WEB_RECON"

            vuln_agent = await uow.agents.get_by_id("agent-vuln-01")
            assert vuln_agent is not None
            assert vuln_agent.status.upper() == AgentStatus.RECOVERY.value

            sentinel_agent = await uow.agents.get_by_id("agent-sentinel-01")
            assert sentinel_agent is not None
            assert sentinel_agent.status.upper() == AgentStatus.IDLE.value

        # Assert in-memory registry contains all live handles with FSM in RECOVERY
        recon_handle = await registry.get("agent-recon-01")
        assert recon_handle is not None
        assert recon_handle.current_state == AgentLifecycleState.RECOVERY
        assert recon_handle.current_task_id == "TASK_WEB_RECON"

        vuln_handle = await registry.get("agent-vuln-01")
        assert vuln_handle is not None
        assert vuln_handle.current_state == AgentLifecycleState.RECOVERY

        sentinel_handle = await registry.get("agent-sentinel-01")
        assert sentinel_handle is not None
        assert sentinel_handle.current_state == AgentLifecycleState.IDLE
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_integration_backend_kill_and_restart_reconciliation():
    """Integration Test: Simulate mid-task kill of the backend and verify that restarting the

    FastAPI lifespan reconciles all orphaned agents.
    """
    session_factory, engine = await setup_test_environment()
    try:
        # Step 1: Create custom agent running a task
        async with UnitOfWork(session_factory) as uow:
            await uow.agents.create_agent(
                AgentCreateRequest(
                    id="agent-custom-recon",
                    role_id="role_web_discovery",
                    department_id="dept_recon",
                    display_name="Custom Recon Agent",
                    status=AgentStatus.RUNNING,
                    current_task_id="TASK_WEB_RECON",
                )
            )
            await uow.commit()

        # Step 2: Simulate restart by running reconcile_with_db on a fresh registry instance
        fresh_registry = AgentRegistry()
        report = await fresh_registry.reconcile_with_db(session_factory)

        assert "agent-custom-recon" in report.reconciled_agent_ids

        # Step 3: Verify the agent runtime handle is available in memory in RECOVERY state
        handle = await fresh_registry.get("agent-custom-recon")
        assert handle is not None
        assert handle.current_state == AgentLifecycleState.RECOVERY
        assert handle.current_task_id == "TASK_WEB_RECON"

        # Verify FSM allows transition from RECOVERY to PLANNING or PREPARING for retry
        assert (
            handle.state_machine.can_transition_to(AgentLifecycleState.PREPARING)
            is True
        )
        handle.state_machine.transition_to(AgentLifecycleState.PREPARING)
        assert handle.current_state == AgentLifecycleState.PREPARING
    finally:
        await engine.dispose()
