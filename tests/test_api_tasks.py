"""Integration tests for Task CRUD REST endpoints, multi-filter queries, and audited manual status overrides."""

import pytest
from app.api.tasks import get_uow_dependency
from app.domain.engagement import Base, EngagementCreateRequest
from app.domain.task import TaskCreateRequest, TaskStatus
from app.main import create_app
from app.repositories.unit_of_work import UnitOfWork
from app.services.org_bootstrap import OrgBootstrapService
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_environment():
    """Setup test SQLite database, seed org, engagement, and a cluster of test tasks."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    bootstrap = OrgBootstrapService(session_factory)
    await bootstrap.bootstrap_organization()

    async with UnitOfWork(session_factory) as uow:
        # Create test engagement
        await uow.engagements.create_engagement(
            EngagementCreateRequest(
                engagement_id="eng-api-task-test",
                title="API Task Test Engagement",
                organization="TestSec",
                authorized_by="CISO",
            )
        )
        # Task 1: Recon (READY, Priority 3, Agent agent-recon-01)
        t1 = await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_01_RECON",
                engagement_id="eng-api-task-test",
                department_id="dept_recon",
                title="DNS & Subdomain Recon",
                assigned_role="role_web_discovery",
                assigned_agent_id="agent-recon-01",
                priority=3,
            )
        )
        await uow.tasks.update_status(t1.task_id, TaskStatus.READY)

        # Task 2: Port Scanning (PENDING, Priority 2, depends on Task 1)
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_02_PORTS",
                engagement_id="eng-api-task-test",
                department_id="dept_recon",
                title="Active Port Scan",
                assigned_role="role_network_mapper",
                assigned_agent_id=None,
                depends_on=["TASK_01_RECON"],
                priority=2,
            )
        )

        # Task 3: Vulnerability Scan (RUNNING, Priority 4, dept_vuln_assessment, Agent agent-vuln-01)
        t3 = await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_03_VULN",
                engagement_id="eng-api-task-test",
                department_id="dept_vuln_assessment",
                title="Web Vulnerability Assessment",
                assigned_role="role_vulnerability_scanner",
                assigned_agent_id="agent-vuln-01",
                priority=4,
            )
        )
        await uow.tasks.update_status(t3.task_id, TaskStatus.RUNNING)

        # Task 4: Report Generation (COMPLETED, Priority 1, dept_reporting, Agent agent-report-01)
        t4 = await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_04_REPORT",
                engagement_id="eng-api-task-test",
                department_id="dept_reporting",
                title="Executive Summary Draft",
                assigned_role="role_technical_writer",
                assigned_agent_id="agent-report-01",
                priority=1,
            )
        )
        await uow.tasks.update_status(t4.task_id, TaskStatus.COMPLETED)

        await uow.commit()

    return session_factory, engine


@pytest.mark.asyncio
async def test_get_tasks_all_and_filtering():
    """Verify GET /api/v1/tasks lists all tasks and filters correctly across dimensions."""
    session_factory, engine = await setup_test_environment()
    try:
        app = create_app()
        app.dependency_overrides[get_uow_dependency] = lambda: session_factory

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 1. List all tasks
            res = await client.get("/api/v1/tasks")
            assert res.status_code == 200
            tasks = res.json()
            assert len(tasks) == 4

            # 2. Filter by department
            res_recon = await client.get("/api/v1/tasks?department_id=dept_recon")
            assert res_recon.status_code == 200
            recon_tasks = res_recon.json()
            assert len(recon_tasks) == 2
            assert all(t["department_id"] == "dept_recon" for t in recon_tasks)

            # 3. Filter by status (READY)
            res_ready = await client.get("/api/v1/tasks?status=ready")
            assert res_ready.status_code == 200
            ready_tasks = res_ready.json()
            assert len(ready_tasks) == 1
            assert ready_tasks[0]["task_id"] == "TASK_01_RECON"

            # 4. Filter by assigned agent
            res_agent = await client.get("/api/v1/tasks?agent_id=agent-vuln-01")
            assert res_agent.status_code == 200
            agent_tasks = res_agent.json()
            assert len(agent_tasks) == 1
            assert agent_tasks[0]["task_id"] == "TASK_03_VULN"

            # 5. Filter by priority (>= 4)
            res_prio = await client.get("/api/v1/tasks?priority=4")
            assert res_prio.status_code == 200
            prio_tasks = res_prio.json()
            assert len(prio_tasks) == 1
            assert prio_tasks[0]["task_id"] == "TASK_03_VULN"

            # 6. Pagination (limit=2, offset=1)
            res_pag = await client.get("/api/v1/tasks?limit=2&offset=1")
            assert res_pag.status_code == 200
            pag_tasks = res_pag.json()
            assert len(pag_tasks) == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_task_by_id_and_dependency_edges():
    """Verify GET /api/v1/tasks/{id} returns full task details with depends_on and blocks relations."""
    session_factory, engine = await setup_test_environment()
    try:
        app = create_app()
        app.dependency_overrides[get_uow_dependency] = lambda: session_factory

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Get Task 1 (should block Task 2)
            res1 = await client.get("/api/v1/tasks/TASK_01_RECON")
            assert res1.status_code == 200
            data1 = res1.json()
            assert data1["task_id"] == "TASK_01_RECON"
            assert "TASK_02_PORTS" in data1["blocks"]

            # Get Task 2 (should depend on Task 1)
            res2 = await client.get("/api/v1/tasks/TASK_02_PORTS")
            assert res2.status_code == 200
            data2 = res2.json()
            assert data2["task_id"] == "TASK_02_PORTS"
            assert "TASK_01_RECON" in data2["depends_on"]

            # Nonexistent task -> 404
            res_404 = await client.get("/api/v1/tasks/TASK_NONEXISTENT")
            assert res_404.status_code == 404
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_manual_task_override_gating_and_audit_logging():
    """Technical Decision & Acceptance Criteria: Manual override endpoint is gated behind an

    explicit admin/debug flag and strictly logged to the immutable audit store.
    """
    session_factory, engine = await setup_test_environment()
    try:
        app = create_app()
        app.dependency_overrides[get_uow_dependency] = lambda: session_factory

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 1. Attempt override WITHOUT admin header or body flag -> 403 Forbidden
            res_denied = await client.patch(
                "/api/v1/tasks/TASK_02_PORTS",
                json={
                    "status": "ready",
                    "reason": "Unauthorized bypass attempt",
                    "admin_override": False,
                },
            )
            assert res_denied.status_code == 403
            assert "restricted to admin/debug use" in res_denied.json()["detail"]

            # 2. Execute authorized override WITH header 'X-Admin-Override: true'
            res_header = await client.patch(
                "/api/v1/tasks/TASK_02_PORTS",
                headers={"X-Admin-Override": "true"},
                json={
                    "status": "ready",
                    "reason": "Operator manually unblocked task after external DNS sync",
                    "actor_id": "operator-vedant",
                },
            )
            assert res_header.status_code == 200
            updated_data = res_header.json()
            assert updated_data["status"] == "READY"

            # 3. Execute authorized override WITH payload 'admin_override: true'
            res_body = await client.patch(
                "/api/v1/tasks/TASK_03_VULN",
                json={
                    "status": "completed",
                    "reason": "Emergency sign-off by CISO",
                    "admin_override": True,
                    "actor_id": "ciso-admin",
                },
            )
            assert res_body.status_code == 200
            assert res_body.json()["status"] == "COMPLETED"

            # 4. Verify Immutable Audit Trail contains both override audit events
            async with UnitOfWork(session_factory) as uow:
                audit_events = await uow.audit.list_by_engagement("eng-api-task-test")
                override_events = [
                    e
                    for e in audit_events
                    if e.event_type == "task_status_manually_overridden"
                ]
                assert len(override_events) == 2

                # Verify payload structure in audit
                p1 = override_events[0].payload
                assert p1["task_id"] == "TASK_02_PORTS"
                assert p1["new_status"] == "READY"
                assert p1["admin_override"] is True

                p2 = override_events[1].payload
                assert p2["task_id"] == "TASK_03_VULN"
                assert p2["new_status"] == "COMPLETED"
                assert p2["actor_id"] == "ciso-admin"
    finally:
        await engine.dispose()
