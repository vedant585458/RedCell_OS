"""Unit tests for DepartmentStaffingService, capacity calculations, and bounded auto-hiring."""

import pytest
from app.domain.engagement import Base, EngagementCreateRequest
from app.domain.task import TaskCreateRequest, TaskStatus
from app.repositories.unit_of_work import UnitOfWork
from app.services.org_bootstrap import OrgBootstrapService
from app.services.staffing import (
    DepartmentLoadState,
    DepartmentStaffingService,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_environment():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Bootstrap default departments and roles
    bootstrap = OrgBootstrapService(session_factory)
    await bootstrap.bootstrap_organization()

    # Create an engagement to test against
    async with UnitOfWork(session_factory) as uow:
        await uow.engagements.create_engagement(
            EngagementCreateRequest(
                engagement_id="eng-staff-001",
                title="Staffing Evaluation Engagement",
                organization="Acme Labs",
                authorized_by="Lead CISO",
            )
        )
        await uow.commit()

    return session_factory, engine


@pytest.mark.asyncio
async def test_department_capacity_calculation():
    session_factory, engine = await setup_test_environment()
    try:
        service = DepartmentStaffingService(
            session_factory=session_factory, max_agents_per_department=5
        )

        # 1. Initial State: dept_vulnerability has 1 idle agent (agent-vuln-01), 0 tasks -> UNDERUTILIZED
        cap_init = await service.evaluate_department_capacity("dept_vulnerability")
        assert cap_init.department_id == "dept_vulnerability"
        assert cap_init.total_agents == 1
        assert cap_init.idle_agents == 1
        assert cap_init.busy_agents == 0
        assert cap_init.capacity_deficit == 0
        assert cap_init.load_state == DepartmentLoadState.UNDERUTILIZED

        # 2. Add 3 unassigned READY tasks to dept_vulnerability
        async with UnitOfWork(session_factory) as uow:
            for i in range(1, 4):
                t = await uow.tasks.create_task(
                    TaskCreateRequest(
                        task_id=f"TASK_VULN_{i}",
                        engagement_id="eng-staff-001",
                        department_id="dept_vulnerability",
                        title=f"Web Vuln Scan {i}",
                        assigned_role="role_web_vuln_assessor",
                    )
                )
                await uow.tasks.update_status(t.task_id, TaskStatus.READY)
            await uow.commit()

        # 3. Re-evaluate capacity: 3 ready tasks - 1 idle agent = deficit of 2 -> OVERLOADED
        cap_overloaded = await service.evaluate_department_capacity(
            "dept_vulnerability"
        )
        assert cap_overloaded.unassigned_ready_tasks == 3
        assert cap_overloaded.capacity_deficit == 2
        assert cap_overloaded.load_state == DepartmentLoadState.OVERLOADED
        assert cap_overloaded.can_hire_more is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_auto_staffing_executes_hires_and_assigns_tasks():
    session_factory, engine = await setup_test_environment()
    try:
        service = DepartmentStaffingService(
            session_factory=session_factory, max_agents_per_department=5
        )

        # Seed 3 unassigned ready tasks
        async with UnitOfWork(session_factory) as uow:
            for i in range(1, 4):
                t = await uow.tasks.create_task(
                    TaskCreateRequest(
                        task_id=f"TASK_CLOUD_{i}",
                        engagement_id="eng-staff-001",
                        department_id="dept_vulnerability",
                        title=f"Cloud Assessment {i}",
                        assigned_role="role_cloud_container_assessor",  # Unstaffed role!
                    )
                )
                await uow.tasks.update_status(t.task_id, TaskStatus.READY)
            await uow.commit()

        # 1. Evaluate recommendations
        recs = await service.evaluate_staffing_needs("dept_vulnerability")
        assert len(recs) == 1
        assert recs[0].role_id == "role_cloud_container_assessor"
        assert recs[0].hire_count >= 2

        # 2. Auto-staff department
        hired_agents = await service.auto_staff_department("dept_vulnerability")
        assert len(hired_agents) >= 2

        # 3. Verify in DB that new agents exist and tasks are now assigned
        async with UnitOfWork(session_factory) as uow:
            assigned_tasks = await uow.tasks.list_by_department(
                "dept_vulnerability", status=TaskStatus.RUNNING
            )
            assert len(assigned_tasks) >= 2
            for t in assigned_tasks:
                assert t.assigned_agent_id is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_anti_runaway_agent_creation_cap():
    session_factory, engine = await setup_test_environment()
    try:
        # Strict max cap of 3 agents for dept_recon
        max_cap = 3
        service = DepartmentStaffingService(
            session_factory=session_factory, max_agents_per_department=max_cap
        )

        # Create 15 unassigned ready tasks (a large workload burst)
        async with UnitOfWork(session_factory) as uow:
            for i in range(1, 16):
                t = await uow.tasks.create_task(
                    TaskCreateRequest(
                        task_id=f"TASK_MASSIVE_BURST_{i}",
                        engagement_id="eng-staff-001",
                        department_id="dept_recon",
                        title=f"Burst Task {i}",
                        assigned_role="role_web_discovery",
                    )
                )
                await uow.tasks.update_status(t.task_id, TaskStatus.READY)
            await uow.commit()

        # Auto-staff must strictly enforce the max cap of 3
        await service.auto_staff_department("dept_recon")

        # Verify total agents in dept_recon does NOT exceed max_cap (3)
        async with UnitOfWork(session_factory) as uow:
            recon_agents = await uow.agents.list_by_department("dept_recon")
            assert len(recon_agents) <= max_cap
            assert len(recon_agents) == max_cap

            # Re-evaluating capacity should show AT_CAPACITY and can_hire_more=False
            cap_status = await service.evaluate_department_capacity("dept_recon")
            assert cap_status.can_hire_more is False
            assert cap_status.total_agents == max_cap
    finally:
        await engine.dispose()
