"""Integration tests for PlanMaterializer converting CISO plans into persisted Task DAGs and AI Employees."""

import pytest
from app.ciso.materializer import PlanMaterializer
from app.ciso.planner import CisoStrategicPlan, PlannedTask
from app.domain.engagement import Base, EngagementCreateRequest
from app.domain.task import TaskStatus
from app.repositories.unit_of_work import UnitOfWork
from app.services.org_bootstrap import OrgBootstrapService
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_environment():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Bootstrap default departments and roles
    bootstrap = OrgBootstrapService(session_factory)
    await bootstrap.bootstrap_organization()

    # Create an engagement to materialize into
    async with UnitOfWork(session_factory) as uow:
        await uow.engagements.create_engagement(
            EngagementCreateRequest(
                engagement_id="eng-mat-001",
                title="Materializer Test Engagement",
                organization="Acme Labs",
                authorized_by="Lead CISO",
            )
        )
        await uow.commit()

    return session_factory, engine


@pytest.mark.asyncio
async def test_plan_materializer_3_task_dag():
    session_factory, engine = await setup_test_environment()
    try:
        materializer = PlanMaterializer(session_factory=session_factory)

        sample_plan = CisoStrategicPlan(
            engagement_id="eng-mat-001",
            mission_title="Staging Perimeter Assessment",
            departments_involved=["dept_recon", "dept_vulnerability", "dept_reporting"],
            tasks=[
                PlannedTask(
                    task_id="TASK_01_RECON",
                    title="Scan Target Attack Surface",
                    department_id="dept_recon",
                    assigned_role="role_web_discovery",
                    priority=3,
                    depends_on_task_ids=[],
                    success_criteria="Endpoints discovered",
                ),
                PlannedTask(
                    task_id="TASK_02_VULN_SCAN",
                    title="Validate Sensitive Configuration Exposure",
                    department_id="dept_vulnerability",
                    assigned_role="role_web_vuln_assessor",
                    priority=3,
                    depends_on_task_ids=["TASK_01_RECON"],
                    requires_approval_gate="ACTIVE_EXPLOITATION_PROBE",
                    success_criteria="Vulnerabilities recorded",
                ),
                PlannedTask(
                    task_id="TASK_03_REPORT",
                    title="Compile Assessment Report",
                    department_id="dept_reporting",
                    assigned_role="role_technical_writer",
                    priority=2,
                    depends_on_task_ids=["TASK_02_VULN_SCAN"],
                    success_criteria="Markdown report ready",
                ),
            ],
            total_tasks=3,
        )

        result = await materializer.materialize_plan(sample_plan)

        assert result.engagement_id == "eng-mat-001"
        assert result.tasks_created == 3
        assert result.dependencies_created == 2
        assert len(result.materialized_tasks) == 3

        # Verify Database Contents via UnitOfWork
        async with UnitOfWork(session_factory) as uow:
            # 1. Verify Task 1 (Root task should be READY)
            t1 = await uow.tasks.get_task_response("TASK_01_RECON")
            assert t1 is not None
            assert t1.status == TaskStatus.READY
            assert t1.depends_on == []
            assert t1.blocks == ["TASK_02_VULN_SCAN"]
            assert t1.assigned_agent_id is not None

            # 2. Verify Task 2 (Dependent task should be PENDING)
            t2 = await uow.tasks.get_task_response("TASK_02_VULN_SCAN")
            assert t2 is not None
            assert t2.status == TaskStatus.PENDING
            assert t2.depends_on == ["TASK_01_RECON"]
            assert t2.blocks == ["TASK_03_REPORT"]
            assert t2.requires_approval_gate == "ACTIVE_EXPLOITATION_PROBE"

            # 3. Verify Task 3
            t3 = await uow.tasks.get_task_response("TASK_03_REPORT")
            assert t3 is not None
            assert t3.status == TaskStatus.PENDING
            assert t3.depends_on == ["TASK_02_VULN_SCAN"]

            # 4. Verify Engagement status updated to ACTIVE
            eng = await uow.engagements.get_engagement_response("eng-mat-001")
            assert eng is not None
            assert eng.status == "ACTIVE"

            # 5. Verify Audit Log entry
            audits = await uow.audit.list_by_engagement("eng-mat-001")
            assert any(a.event_type == "plan_materialized" for a in audits)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_plan_materializer_dynamic_hiring_unstaffed_role():
    session_factory, engine = await setup_test_environment()
    try:
        materializer = PlanMaterializer(session_factory=session_factory)

        # Plan with an unstaffed specialist role (e.g. role_cloud_container_assessor)
        cloud_plan = CisoStrategicPlan(
            engagement_id="eng-mat-001",
            mission_title="Cloud Audit Mission",
            tasks=[
                PlannedTask(
                    task_id="TASK_CLOUD_01",
                    title="Audit Cloud IAM & Open S3 Buckets",
                    department_id="dept_vulnerability",
                    assigned_role="role_cloud_container_assessor",  # Initially unstaffed!
                    priority=3,
                    depends_on_task_ids=[],
                )
            ],
            total_tasks=1,
        )

        result = await materializer.materialize_plan(cloud_plan)
        assert result.tasks_created == 1
        assert result.agents_hired == 1

        async with UnitOfWork(session_factory) as uow:
            t = await uow.tasks.get_task_response("TASK_CLOUD_01")
            assert t is not None
            assert t.assigned_agent_id is not None
            assert "cloud-container-assessor" in t.assigned_agent_id

            # Verify the new AI employee exists in database
            agent = await uow.agents.get_agent_response(t.assigned_agent_id)
            assert agent is not None
            assert agent.role_id == "role_cloud_container_assessor"
            assert agent.department_id == "dept_vulnerability"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_plan_materializer_atomic_rollback_on_failure():
    session_factory, engine = await setup_test_environment()
    try:
        materializer = PlanMaterializer(session_factory=session_factory)

        # Plan with an invalid self-dependency that will fail
        faulty_plan = CisoStrategicPlan(
            engagement_id="eng-mat-001",
            mission_title="Faulty Mission",
            tasks=[
                PlannedTask(
                    task_id="TASK_FAULTY_01",
                    title="Faulty Task",
                    department_id="dept_recon",
                    assigned_role="role_web_discovery",
                    depends_on_task_ids=["TASK_FAULTY_01"],  # Illegal self-dependency!
                )
            ],
            total_tasks=1,
        )

        with pytest.raises(ValueError):
            await materializer.materialize_plan(faulty_plan)

        # Verify atomic rollback: 0 tasks persisted
        async with UnitOfWork(session_factory) as uow:
            tasks = await uow.tasks.list_by_engagement("eng-mat-001")
            assert len(tasks) == 0
    finally:
        await engine.dispose()
