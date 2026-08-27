"""Unit and integration tests for AssignmentService, LRU agent matching, staffing fallback, and concurrency race-condition protection."""

import asyncio

import pytest
from app.domain.agent import AgentCreateRequest, AgentStatus
from app.domain.engagement import Base, EngagementCreateRequest
from app.domain.task import TaskCreateRequest, TaskStatus
from app.orchestrator import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork
from app.scheduling.assignment import AssignmentService
from app.services.org_bootstrap import OrgBootstrapService
from app.services.staffing import DepartmentStaffingService
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_environment():
    """Setup test SQLite database, seed org, engagement, and baseline tasks."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    bootstrap = OrgBootstrapService(session_factory)
    await bootstrap.bootstrap_organization()

    async with UnitOfWork(session_factory) as uow:
        await uow.engagements.create_engagement(
            EngagementCreateRequest(
                engagement_id="eng-assign-test",
                title="Assignment Service Test Engagement",
                organization="CyberRange Corp",
                authorized_by="CISO",
            )
        )
        # Task 1: Web Recon (Requires role_web_discovery in dept_recon)
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_WEB_RECON",
                engagement_id="eng-assign-test",
                department_id="dept_recon",
                title="Web Subdomain Recon",
                assigned_role="role_web_discovery",
                priority=3,
            )
        )
        await uow.tasks.update_status("TASK_WEB_RECON", TaskStatus.READY)
        await uow.commit()

    return session_factory, engine


@pytest.mark.asyncio
async def test_assignment_match_success_and_lru_selection():
    """Acceptance Criteria: Task matched to correct-capability idle agent using Least-Recently-Used (LRU) tie-breaking."""
    session_factory, engine = await setup_test_environment()
    try:
        # Create 2 idle agents for role_web_discovery with different updated_at timestamps
        async with UnitOfWork(session_factory) as uow:
            # Older agent (idle for longer -> should be chosen first by LRU)
            await uow.agents.create_agent(
                AgentCreateRequest(
                    id="agent-recon-lru-old",
                    role_id="role_web_discovery",
                    department_id="dept_recon",
                    display_name="Old Idle Agent",
                    status=AgentStatus.IDLE,
                )
            )
            # Newer agent
            await uow.agents.create_agent(
                AgentCreateRequest(
                    id="agent-recon-lru-new",
                    role_id="role_web_discovery",
                    department_id="dept_recon",
                    display_name="New Idle Agent",
                    status=AgentStatus.IDLE,
                )
            )
            await uow.commit()

        captured_events = []

        async def capture_event(event):
            captured_events.append(event)

        global_orchestrator.register_event_subscriber(capture_event)
        await global_orchestrator.start()

        service = AssignmentService(session_factory)
        result = await service.assign_task("TASK_WEB_RECON")

        assert result.success is True
        assert result.task_id == "TASK_WEB_RECON"
        # LRU selection: Oldest idle agent in department selected
        assert result.assigned_agent_id in ("agent-recon-01", "agent-recon-lru-old")
        assert result.assigned_role == "role_web_discovery"

        # Verify DB reflects atomic update
        async with UnitOfWork(session_factory) as uow:
            task = await uow.tasks.get_by_id("TASK_WEB_RECON")
            assert task is not None
            assert task.status == TaskStatus.RUNNING
            assert task.assigned_agent_id == result.assigned_agent_id

            agent = await uow.agents.get_by_id(result.assigned_agent_id)
            assert agent is not None
            assert agent.status == AgentStatus.ASSIGNED
            assert agent.current_task_id == "TASK_WEB_RECON"

        await asyncio.sleep(0.05)

        # Verify emitted events
        event_types = [e.event_type for e in captured_events]
        assert "task_assigned" in event_types
        assert "agent_state_changed" in event_types
    finally:
        global_orchestrator.unregister_event_subscriber(capture_event)
        await global_orchestrator.stop()
        await engine.dispose()


@pytest.mark.asyncio
async def test_no_agent_available_triggers_staffing_fallback():
    """Acceptance Criteria: No idle agent available path triggers staffing service auto-hiring."""
    session_factory, engine = await setup_test_environment()
    try:
        # Create a task requiring role_cloud_container_assessor in dept_vulnerability (0 agents currently exist)
        async with UnitOfWork(session_factory) as uow:
            await uow.tasks.create_task(
                TaskCreateRequest(
                    task_id="TASK_CLOUD_AUDIT",
                    engagement_id="eng-assign-test",
                    department_id="dept_vulnerability",
                    title="AWS S3 Bucket & IAM Audit",
                    assigned_role="role_cloud_container_assessor",
                    priority=4,
                )
            )
            await uow.tasks.update_status("TASK_CLOUD_AUDIT", TaskStatus.READY)
            await uow.commit()

        service = AssignmentService(session_factory)
        result = await service.assign_task("TASK_CLOUD_AUDIT")

        assert result.success is True
        assert result.task_id == "TASK_CLOUD_AUDIT"
        assert result.hired_new_agent is True
        assert result.assigned_agent_id is not None
        assert result.assigned_role == "role_cloud_container_assessor"
        assert result.department_id == "dept_vulnerability"

        # Verify newly hired agent exists in DB and is ASSIGNED
        async with UnitOfWork(session_factory) as uow:
            agent = await uow.agents.get_by_id(result.assigned_agent_id)
            assert agent is not None
            assert agent.role_id == "role_cloud_container_assessor"
            assert agent.department_id == "dept_vulnerability"
            assert agent.status == AgentStatus.ASSIGNED
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_department_at_max_capacity_and_busy_fails_gracefully():
    """Verify department at maximum capacity with all agents busy fails assignment gracefully without errors."""
    session_factory, engine = await setup_test_environment()
    try:
        # Fill dept_exploitation with max agents (2), all RUNNING
        async with UnitOfWork(session_factory) as uow:
            for i in range(1, 3):
                await uow.agents.create_agent(
                    AgentCreateRequest(
                        id=f"agent-busy-exploit-{i}",
                        role_id="role_exploit_verifier",
                        department_id="dept_exploitation",
                        display_name=f"Busy Exploit Dev {i}",
                        status=AgentStatus.RUNNING,
                    )
                )

            await uow.tasks.create_task(
                TaskCreateRequest(
                    task_id="TASK_EXPLOIT_POC",
                    engagement_id="eng-assign-test",
                    department_id="dept_exploitation",
                    title="Heap Overflow PoC",
                    assigned_role="role_exploit_verifier",
                    priority=4,
                )
            )
            await uow.tasks.update_status("TASK_EXPLOIT_POC", TaskStatus.READY)
            await uow.commit()

        # Staffing service configured with max_agents_per_department=2
        staffing_service = DepartmentStaffingService(
            session_factory, max_agents_per_department=2
        )
        service = AssignmentService(session_factory, staffing_service=staffing_service)

        result = await service.assign_task("TASK_EXPLOIT_POC")

        assert result.success is False
        assert result.assigned_agent_id is None
        assert "maximum staffing capacity" in result.reason

        # Task remains in READY status
        async with UnitOfWork(session_factory) as uow:
            task = await uow.tasks.get_by_id("TASK_EXPLOIT_POC")
            assert task is not None
            assert task.status == TaskStatus.READY
            assert task.assigned_agent_id is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_assignment_race_condition_protection():
    """Risk Mitigation Test: Prevent double-booking race conditions when concurrent tasks compete for the same agent."""
    session_factory, engine = await setup_test_environment()
    try:
        # Create exactly 1 idle specialist agent in dept_recon
        async with UnitOfWork(session_factory) as uow:
            await uow.agents.create_agent(
                AgentCreateRequest(
                    id="agent-solo-mapper",
                    role_id="role_network_mapper",
                    department_id="dept_recon",
                    display_name="Solo Mapper Agent",
                    status=AgentStatus.IDLE,
                )
            )

            # Create 2 concurrent tasks both requiring role_network_mapper
            for i in range(1, 3):
                await uow.tasks.create_task(
                    TaskCreateRequest(
                        task_id=f"TASK_MAPPER_{i}",
                        engagement_id="eng-assign-test",
                        department_id="dept_recon",
                        title=f"Parallel Map {i}",
                        assigned_role="role_network_mapper",
                        priority=3,
                    )
                )
                await uow.tasks.update_status(f"TASK_MAPPER_{i}", TaskStatus.READY)

            await uow.commit()

        service = AssignmentService(session_factory)

        # Execute concurrent assignments simultaneously
        results = await asyncio.gather(
            service.assign_task("TASK_MAPPER_1"),
            service.assign_task("TASK_MAPPER_2"),
        )

        assigned_agent_ids = [r.assigned_agent_id for r in results if r.success]

        # Both tasks must NOT be assigned to the same agent instance simultaneously!
        assert len(set(assigned_agent_ids)) == len(assigned_agent_ids)
        assert len(assigned_agent_ids) == 2  # One got solo-mapper, one got auto-hired!
    finally:
        await engine.dispose()
