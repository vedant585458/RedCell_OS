"""Integration tests for TaskReadinessListener, event-driven DAG unblocking, and TaskReady emissions on diamond graphs."""

import asyncio

import pytest
from app.domain.engagement import Base, EngagementCreateRequest
from app.domain.task import TaskCreateRequest, TaskStatus
from app.orchestrator import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork
from app.services.org_bootstrap import OrgBootstrapService
from app.tasks.readiness_listener import TaskReadinessListener
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_environment():
    """Setup test SQLite database, seed org, and build a Diamond Dependency Graph."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    bootstrap = OrgBootstrapService(session_factory)
    await bootstrap.bootstrap_organization()

    async with UnitOfWork(session_factory) as uow:
        # Create engagement
        await uow.engagements.create_engagement(
            EngagementCreateRequest(
                engagement_id="eng-diamond-test",
                title="Diamond Graph Readiness Test",
                organization="TargetOrg",
                authorized_by="CISO",
            )
        )

        # 1. Root Task A: Target Recon (Initial status: READY)
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_A_RECON",
                engagement_id="eng-diamond-test",
                department_id="dept_recon",
                title="Target Scope Recon",
                assigned_role="role_web_discovery",
            )
        )
        await uow.tasks.update_status("TASK_A_RECON", TaskStatus.READY)

        # 2. Branch Task B: Port Scan (Depends on A, Initial: PENDING)
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_B_PORTS",
                engagement_id="eng-diamond-test",
                department_id="dept_recon",
                title="Network Port Scan",
                assigned_role="role_network_mapper",
                depends_on=["TASK_A_RECON"],
            )
        )

        # 3. Branch Task C: DNS Enumeration (Depends on A, Initial: PENDING)
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_C_DNS",
                engagement_id="eng-diamond-test",
                department_id="dept_recon",
                title="Subdomain DNS Brute",
                assigned_role="role_web_discovery",
                depends_on=["TASK_A_RECON"],
            )
        )

        # 4. Sink Task D: Vuln Assessment (Depends on BOTH B and C, Initial: PENDING)
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_D_VULN",
                engagement_id="eng-diamond-test",
                department_id="dept_vuln_assessment",
                title="Consolidated Vulnerability Scan",
                assigned_role="role_vulnerability_scanner",
                depends_on=["TASK_B_PORTS", "TASK_C_DNS"],
            )
        )

        await uow.commit()

    return session_factory, engine


@pytest.mark.asyncio
async def test_diamond_dependency_readiness_listener_cascade():
    """Acceptance Criteria: Event listener unblocks downstream tasks on TaskCompleted events

    and emits TaskReady events when all dependencies clear on a diamond dependency graph.
    """
    session_factory, engine = await setup_test_environment()
    try:
        listener = TaskReadinessListener(session_factory)
        listener.start_listening()

        captured_events = []

        async def capture_event(event):
            captured_events.append(event)

        global_orchestrator.register_event_subscriber(capture_event)
        await global_orchestrator.start()

        # ======================================================================
        # Step 1: Complete Root Task A -> Unblocks Task B and Task C
        # ======================================================================
        async with UnitOfWork(session_factory) as uow:
            await uow.tasks.update_status("TASK_A_RECON", TaskStatus.COMPLETED)
            await uow.commit()

        # Emit task_completed event for Task A
        await global_orchestrator.emit_event(
            event_type="task_completed",
            correlation_id="corr-test-01",
            engagement_id="eng-diamond-test",
            task_id="TASK_A_RECON",
            payload={"task_id": "TASK_A_RECON"},
        )

        await asyncio.sleep(0.05)

        # Verify DB: Tasks B and C are now READY; Task D is still PENDING
        async with UnitOfWork(session_factory) as uow:
            tb = await uow.tasks.get_by_id("TASK_B_PORTS")
            assert tb is not None and tb.status == TaskStatus.READY
            tc = await uow.tasks.get_by_id("TASK_C_DNS")
            assert tc is not None and tc.status == TaskStatus.READY
            td = await uow.tasks.get_by_id("TASK_D_VULN")
            assert td is not None and td.status == TaskStatus.PENDING

        # Verify TaskReady events were emitted for B and C
        ready_events_1 = [e for e in captured_events if e.event_type == "task_ready"]
        ready_task_ids_1 = {e.task_id for e in ready_events_1}
        assert "TASK_B_PORTS" in ready_task_ids_1
        assert "TASK_C_DNS" in ready_task_ids_1
        assert "TASK_D_VULN" not in ready_task_ids_1

        # ======================================================================
        # Step 2: Complete Task B (Partial prerequisite for Task D)
        # ======================================================================
        async with UnitOfWork(session_factory) as uow:
            await uow.tasks.update_status("TASK_B_PORTS", TaskStatus.COMPLETED)
            await uow.commit()

        await global_orchestrator.emit_event(
            event_type="task_completed",
            correlation_id="corr-test-02",
            engagement_id="eng-diamond-test",
            task_id="TASK_B_PORTS",
            payload={"task_id": "TASK_B_PORTS"},
        )

        await asyncio.sleep(0.05)

        # Task D must remain PENDING because Task C is still incomplete
        async with UnitOfWork(session_factory) as uow:
            td_mid = await uow.tasks.get_by_id("TASK_D_VULN")
            assert td_mid is not None and td_mid.status == TaskStatus.PENDING

        ready_events_2 = [
            e
            for e in captured_events
            if e.event_type == "task_ready" and e.task_id == "TASK_D_VULN"
        ]
        assert len(ready_events_2) == 0

        # ======================================================================
        # Step 3: Complete Task C (FINAL prerequisite for Task D!)
        # ======================================================================
        async with UnitOfWork(session_factory) as uow:
            await uow.tasks.update_status("TASK_C_DNS", TaskStatus.COMPLETED)
            await uow.commit()

        await global_orchestrator.emit_event(
            event_type="task_completed",
            correlation_id="corr-test-03",
            engagement_id="eng-diamond-test",
            task_id="TASK_C_DNS",
            payload={"task_id": "TASK_C_DNS"},
        )

        await asyncio.sleep(0.05)

        # Task D is now READY!
        async with UnitOfWork(session_factory) as uow:
            td_final = await uow.tasks.get_by_id("TASK_D_VULN")
            assert td_final is not None and td_final.status == TaskStatus.READY

        # Verify TaskReady event emitted for Task D with correct metadata
        ready_events_3 = [
            e
            for e in captured_events
            if e.event_type == "task_ready" and e.task_id == "TASK_D_VULN"
        ]
        assert len(ready_events_3) == 1
        payload_d = ready_events_3[0].payload
        assert payload_d["task_id"] == "TASK_D_VULN"
        assert payload_d["unblocked_by_task_id"] == "TASK_C_DNS"
        assert payload_d["department_id"] == "dept_vuln_assessment"
        assert payload_d["assigned_role"] == "role_vulnerability_scanner"
    finally:
        listener.stop_listening()
        global_orchestrator.unregister_event_subscriber(capture_event)
        await global_orchestrator.stop()
        await engine.dispose()


@pytest.mark.asyncio
async def test_wide_fan_out_completion_event_handling():
    """Verify wide fan-out completions unblock multiple dependent tasks cleanly without recursion loops."""
    session_factory, engine = await setup_test_environment()
    try:
        listener = TaskReadinessListener(session_factory)

        # Create 5 parallel subtasks all depending on Task A
        async with UnitOfWork(session_factory) as uow:
            for i in range(1, 6):
                await uow.tasks.create_task(
                    TaskCreateRequest(
                        task_id=f"TASK_FAN_{i}",
                        engagement_id="eng-diamond-test",
                        department_id="dept_recon",
                        title=f"Parallel Scan {i}",
                        assigned_role="role_network_mapper",
                        depends_on=["TASK_A_RECON"],
                    )
                )
            await uow.commit()

        # Complete Task A
        async with UnitOfWork(session_factory) as uow:
            await uow.tasks.update_status("TASK_A_RECON", TaskStatus.COMPLETED)
            await uow.commit()

        unblocked_tasks = await listener.process_task_completion(
            completed_task_id="TASK_A_RECON",
            engagement_id="eng-diamond-test",
            correlation_id="corr-fan-out",
        )

        unblocked_ids = [t.task_id for t in unblocked_tasks]
        # Must unblock all 5 fan-out tasks plus Tasks B and C
        for i in range(1, 6):
            assert f"TASK_FAN_{i}" in unblocked_ids
        assert "TASK_B_PORTS" in unblocked_ids
        assert "TASK_C_DNS" in unblocked_ids
    finally:
        await engine.dispose()
