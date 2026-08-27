"""Integration tests for Department task queue REST API endpoints and SQL-level status aggregations."""

import httpx
import pytest
from app.api.departments import get_uow_dependency
from app.domain.engagement import Base, EngagementCreateRequest
from app.domain.task import TaskCreateRequest, TaskStatus
from app.main import create_app
from app.repositories.unit_of_work import UnitOfWork
from app.services.org_bootstrap import OrgBootstrapService
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_app_with_tasks():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Bootstrap departments and roles
    bootstrap = OrgBootstrapService(session_factory)
    await bootstrap.bootstrap_organization()

    async with UnitOfWork(session_factory) as uow:
        # 1. Create Engagement
        await uow.engagements.create_engagement(
            EngagementCreateRequest(
                engagement_id="eng-dept-test",
                title="Dept Queue Test",
                organization="Acme",
                authorized_by="CISO",
            )
        )

        # 2. Seed mixed status tasks into dept_recon
        # Task 1: PENDING
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_RECON_PENDING",
                engagement_id="eng-dept-test",
                department_id="dept_recon",
                title="Pending Subdomain Scan",
                assigned_role="role_web_discovery",
            )
        )

        # Task 2: RUNNING
        t2 = await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_RECON_RUNNING",
                engagement_id="eng-dept-test",
                department_id="dept_recon",
                title="Running Active Recon",
                assigned_role="role_active_network_recon",
            )
        )
        await uow.tasks.update_status(t2.task_id, TaskStatus.RUNNING)

        # Task 3: COMPLETED
        t3 = await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_RECON_COMPLETED",
                engagement_id="eng-dept-test",
                department_id="dept_recon",
                title="Completed WHOIS Query",
                assigned_role="role_passive_osint",
            )
        )
        await uow.tasks.update_status(t3.task_id, TaskStatus.COMPLETED)

        # Task 4: AWAITING_APPROVAL
        t4 = await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_RECON_APPROVAL",
                engagement_id="eng-dept-test",
                department_id="dept_recon",
                title="Aggressive Port Fuzzing",
                assigned_role="role_active_network_recon",
                requires_approval_gate="HIGH_RATE_FUZZING",
            )
        )
        await uow.tasks.update_status(t4.task_id, TaskStatus.AWAITING_APPROVAL)

        # Task 5: FAILED
        t5 = await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_RECON_FAILED",
                engagement_id="eng-dept-test",
                department_id="dept_recon",
                title="Crashing Probe",
                assigned_role="role_web_discovery",
            )
        )
        await uow.tasks.update_status(t5.task_id, TaskStatus.FAILED)

        await uow.commit()

    app = create_app()
    app.dependency_overrides[get_uow_dependency] = lambda: session_factory

    return app, session_factory, engine


@pytest.mark.asyncio
async def test_get_department_task_queue_sql_aggregation():
    app, _, engine = await setup_test_app_with_tasks()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            res = await client.get("/api/v1/departments/dept_recon/tasks")
            assert res.status_code == 200
            data = res.json()

            assert data["department_id"] == "dept_recon"
            assert data["department_name"] == "Reconnaissance & OSINT Department"

            # Verify SQL-aggregated counts
            counts = data["counts"]
            assert counts["total"] == 5
            assert counts["pending"] == 1
            assert counts["in_progress"] == 1
            assert counts["completed"] == 1
            assert counts["awaiting_approval"] == 1
            assert counts["failed"] == 1

            # Verify paginated task list
            assert len(data["tasks"]) == 5
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_department_task_queue_status_filter():
    app, _, engine = await setup_test_app_with_tasks()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Filter by COMPLETED
            res = await client.get(
                "/api/v1/departments/dept_recon/tasks?status=COMPLETED"
            )
            assert res.status_code == 200
            data = res.json()

            # Counts should still reflect total department health
            assert data["counts"]["total"] == 5
            # Only 1 completed task in filtered list
            assert len(data["tasks"]) == 1
            assert data["tasks"][0]["task_id"] == "TASK_RECON_COMPLETED"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_all_departments_summary():
    app, _, engine = await setup_test_app_with_tasks()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            res = await client.get("/api/v1/departments/tasks/summary")
            assert res.status_code == 200
            data = res.json()

            assert len(data["departments"]) == 7
            assert (
                data["total_active_tasks"] >= 2
            )  # 1 in_progress + 1 awaiting_approval

            recon_summary = next(
                d for d in data["departments"] if d["department_id"] == "dept_recon"
            )
            assert recon_summary["counts"]["total"] == 5
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_non_existent_department_404():
    app, _, engine = await setup_test_app_with_tasks()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            res = await client.get("/api/v1/departments/dept_non_existent/tasks")
            assert res.status_code == 404
    finally:
        await engine.dispose()
