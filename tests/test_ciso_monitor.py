"""Unit and integration tests for CisoProgressMonitor event-driven decision loop."""

import pytest
from app.ciso.materializer import PlanMaterializer
from app.ciso.monitor import (
    MAX_REPLANS_PER_ENGAGEMENT,
    CisoDecisionType,
    CisoProgressMonitor,
)
from app.ciso.planner import CisoStrategicPlan, PlannedTask
from app.domain.engagement import Base, EngagementCreateRequest
from app.domain.task import TaskStatus
from app.orchestrator.models import OrchestratorEvent
from app.repositories.unit_of_work import UnitOfWork
from app.services.org_bootstrap import OrgBootstrapService
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_environment():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Bootstrap departments & roles
    bootstrap = OrgBootstrapService(session_factory)
    await bootstrap.bootstrap_organization()

    # Create engagement
    async with UnitOfWork(session_factory) as uow:
        await uow.engagements.create_engagement(
            EngagementCreateRequest(
                engagement_id="eng-mon-001",
                title="Progress Monitor Test Engagement",
                organization="Acme Labs",
                authorized_by="Lead CISO",
            )
        )
        await uow.commit()

    # Materialize 2-task DAG (Task 1 -> Task 2)
    materializer = PlanMaterializer(session_factory=session_factory)
    await materializer.materialize_plan(
        CisoStrategicPlan(
            engagement_id="eng-mon-001",
            mission_title="2-Task Test Plan",
            tasks=[
                PlannedTask(
                    task_id="TASK_01_RECON",
                    title="Recon Task",
                    department_id="dept_recon",
                    assigned_role="role_web_discovery",
                    depends_on_task_ids=[],
                ),
                PlannedTask(
                    task_id="TASK_02_VULN",
                    title="Vuln Task",
                    department_id="dept_vulnerability",
                    assigned_role="role_web_vuln_assessor",
                    depends_on_task_ids=["TASK_01_RECON"],
                ),
            ],
            total_tasks=2,
        )
    )

    return session_factory, engine


@pytest.mark.asyncio
async def test_ciso_monitor_unblocks_downstream_task():
    session_factory, engine = await setup_test_environment()
    try:
        monitor = CisoProgressMonitor(session_factory=session_factory)

        # Mark Task 1 as COMPLETED
        async with UnitOfWork(session_factory) as uow:
            await uow.tasks.update_status("TASK_01_RECON", TaskStatus.COMPLETED)
            await uow.commit()

        # Simulate task_completed event for Task 1
        event = OrchestratorEvent(
            event_type="task_completed",
            correlation_id="corr-mon-01",
            engagement_id="eng-mon-001",
            task_id="TASK_01_RECON",
        )

        decision = await monitor.handle_event(event)

        assert decision is not None
        assert decision.decision_type == CisoDecisionType.CONTINUE
        assert "TASK_02_VULN" in decision.unblocked_task_ids

        # Verify in DB that Task 2 transitioned to READY
        async with UnitOfWork(session_factory) as uow:
            t2 = await uow.tasks.get_task_response("TASK_02_VULN")
            assert t2 is not None
            assert t2.status == TaskStatus.READY
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ciso_monitor_completes_engagement_when_all_tasks_done():
    session_factory, engine = await setup_test_environment()
    try:
        monitor = CisoProgressMonitor(session_factory=session_factory)

        # Complete both tasks in DB
        async with UnitOfWork(session_factory) as uow:
            await uow.tasks.update_status("TASK_01_RECON", TaskStatus.COMPLETED)
            await uow.tasks.update_status("TASK_02_VULN", TaskStatus.COMPLETED)
            await uow.commit()

        # Send task_completed event for the final task
        event = OrchestratorEvent(
            event_type="task_completed",
            correlation_id="corr-mon-02",
            engagement_id="eng-mon-001",
            task_id="TASK_02_VULN",
        )

        decision = await monitor.handle_event(event)

        assert decision is not None
        assert decision.decision_type == CisoDecisionType.COMPLETE_ENGAGEMENT
        assert "All planned tasks" in decision.reason

        # Verify engagement status updated to COMPLETED
        async with UnitOfWork(session_factory) as uow:
            eng = await uow.engagements.get_engagement_response("eng-mon-001")
            assert eng is not None
            assert eng.status == "COMPLETED"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ciso_monitor_task_failure_and_infinite_replan_stability():
    session_factory, engine = await setup_test_environment()
    try:
        monitor = CisoProgressMonitor(session_factory=session_factory)

        # Failures 1 to MAX_REPLANS_PER_ENGAGEMENT (3) trigger REPLAN
        for attempt in range(1, MAX_REPLANS_PER_ENGAGEMENT + 1):
            fail_event = OrchestratorEvent(
                event_type="task_failed",
                correlation_id=f"corr-fail-{attempt}",
                engagement_id="eng-mon-001",
                task_id="TASK_01_RECON",
                payload={"error": "Connection timeout"},
            )
            decision = await monitor.handle_event(fail_event)
            assert decision is not None
            assert decision.decision_type == CisoDecisionType.REPLAN
            assert decision.replan_count == attempt

        # 4th failure exceeds limit -> must trip ESCALATE_TO_HUMAN
        fourth_event = OrchestratorEvent(
            event_type="task_failed",
            correlation_id="corr-fail-4",
            engagement_id="eng-mon-001",
            task_id="TASK_01_RECON",
            payload={"error": "Repeated persistent crash"},
        )
        escalation_decision = await monitor.handle_event(fourth_event)

        assert escalation_decision is not None
        assert escalation_decision.decision_type == CisoDecisionType.ESCALATE_TO_HUMAN
        assert "maximum replanning limit" in escalation_decision.reason
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ciso_monitor_high_severity_finding_triggers_approval_decision():
    session_factory, engine = await setup_test_environment()
    try:
        monitor = CisoProgressMonitor(session_factory=session_factory)

        finding_event = OrchestratorEvent(
            event_type="finding_recorded",
            correlation_id="corr-find-01",
            engagement_id="eng-mon-001",
            payload={
                "title": "Unauthenticated RCE",
                "severity": "HIGH",
            },
        )

        decision = await monitor.handle_event(finding_event)
        assert decision is not None
        assert decision.decision_type == CisoDecisionType.REQUEST_APPROVAL
    finally:
        await engine.dispose()
