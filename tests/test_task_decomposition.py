"""Unit and integration tests for SubtaskService, recursive task decomposition, priority inheritance, and aggregate parent status derivation."""

import pytest
from app.domain.engagement import Base, EngagementCreateRequest
from app.domain.task import TaskCreateRequest, TaskStatus
from app.repositories.unit_of_work import UnitOfWork
from app.services.org_bootstrap import OrgBootstrapService
from app.tasks.decomposition import (
    DecompositionDepthExceededError,
    ParentTaskNotFoundError,
    ParentTaskTerminalError,
    SubtaskCountExceededError,
    SubtaskService,
    SubtaskSpec,
)
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
                engagement_id="eng-decomp-test",
                title="Task Decomposition Test Engagement",
                organization="CyberRange Corp",
                authorized_by="CISO",
            )
        )
        # Parent Task: Port Scanning (Priority 2, dept_recon)
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_PARENT_SCAN",
                engagement_id="eng-decomp-test",
                department_id="dept_recon",
                title="Comprehensive Infrastructure Port Scan",
                assigned_role="role_network_mapper",
                priority=2,
            )
        )
        await uow.tasks.update_status("TASK_PARENT_SCAN", TaskStatus.READY)
        await uow.commit()

    return session_factory, engine


@pytest.mark.asyncio
async def test_subtask_decomposition_and_priority_inheritance():
    """Verify decomposing a task creates linked subtasks with proper priority inheritance."""
    session_factory, engine = await setup_test_environment()
    try:
        service = SubtaskService(session_factory)

        subtask_specs = [
            # Subtask 1: Explicit priority override to 4
            SubtaskSpec(
                title="TCP Top 1000 Ports",
                description="Fast TCP SYN scan on top ports",
                priority=4,
            ),
            # Subtask 2: Priority omitted -> Should inherit parent's priority 2
            SubtaskSpec(
                title="UDP Common Services Scan",
                description="DNS, SNMP, NTP targeted UDP scan",
                priority=None,
            ),
            # Subtask 3: Department and Role override
            SubtaskSpec(
                title="Banner Grabbing & Service Detection",
                department_id="dept_recon",
                assigned_role="role_web_discovery",
                priority=None,
            ),
        ]

        result = await service.decompose(
            task_id="TASK_PARENT_SCAN",
            subtasks=subtask_specs,
            actor_id="agent-recon-01",
            reason="Decomposing port scan into protocol-specific subtasks",
        )

        assert result.parent_task_id == "TASK_PARENT_SCAN"
        assert len(result.created_subtasks) == 3
        assert result.decomposition_depth == 2

        # 1. Verify Priority Inheritance & Overrides
        subtasks = result.created_subtasks
        assert subtasks[0].priority == 4  # Explicit override
        assert subtasks[1].priority == 2  # Inherited from parent (priority 2)
        assert subtasks[2].priority == 2  # Inherited from parent (priority 2)
        assert subtasks[2].assigned_role == "role_web_discovery"

        # 2. Verify Parent Task is Auto-Blocked in DB while subtasks are active
        async with UnitOfWork(session_factory) as uow:
            parent = await uow.tasks.get_by_id("TASK_PARENT_SCAN")
            assert parent is not None
            assert parent.status == TaskStatus.BLOCKED

            # Verify audit trail
            audit_events = await uow.audit.list_by_engagement("eng-decomp-test")
            decomp_events = [
                e for e in audit_events if e.event_type == "task_decomposed"
            ]
            assert len(decomp_events) == 1
            assert decomp_events[0].payload["subtask_count"] == 3
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_parent_task_auto_completes_when_all_subtasks_complete():
    """Acceptance Criteria & Technical Decision: Parent task status is derived from subtask

    aggregate; parent auto-completes when all child subtasks complete.
    """
    session_factory, engine = await setup_test_environment()
    try:
        service = SubtaskService(session_factory)

        subtasks = [
            SubtaskSpec(title="Subtask Phase 1"),
            SubtaskSpec(title="Subtask Phase 2"),
        ]

        result = await service.decompose(
            task_id="TASK_PARENT_SCAN",
            subtasks=subtasks,
        )
        st1_id = result.created_subtasks[0].task_id
        st2_id = result.created_subtasks[1].task_id

        # Step 1: Subtask 1 completes -> Parent should remain BLOCKED
        async with UnitOfWork(session_factory) as uow:
            await uow.tasks.update_status(st1_id, TaskStatus.COMPLETED)
            await uow.commit()

        parent_after_st1 = await service.reconcile_parent_task("TASK_PARENT_SCAN")
        assert parent_after_st1 is not None
        assert parent_after_st1.status == TaskStatus.BLOCKED

        # Step 2: Subtask 2 completes -> Parent should AUTO-COMPLETE to COMPLETED!
        async with UnitOfWork(session_factory) as uow:
            await uow.tasks.update_status(st2_id, TaskStatus.COMPLETED)
            await uow.commit()

        parent_after_st2 = await service.reconcile_parent_task("TASK_PARENT_SCAN")
        assert parent_after_st2 is not None
        assert parent_after_st2.status == TaskStatus.COMPLETED

        # Verify DB reflects COMPLETED status
        async with UnitOfWork(session_factory) as uow:
            db_parent = await uow.tasks.get_by_id("TASK_PARENT_SCAN")
            assert db_parent is not None
            assert db_parent.status == TaskStatus.COMPLETED
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_subtask_failure_derives_parent_failure():
    """Verify child subtask failure propagates to derive FAILED status on parent task."""
    session_factory, engine = await setup_test_environment()
    try:
        service = SubtaskService(session_factory)

        result = await service.decompose(
            task_id="TASK_PARENT_SCAN",
            subtasks=[SubtaskSpec(title="Sub 1"), SubtaskSpec(title="Sub 2")],
        )
        st1_id = result.created_subtasks[0].task_id

        async with UnitOfWork(session_factory) as uow:
            await uow.tasks.update_status(st1_id, TaskStatus.FAILED)
            await uow.commit()

        parent = await service.reconcile_parent_task("TASK_PARENT_SCAN")
        assert parent is not None
        assert parent.status == TaskStatus.FAILED
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_decomposition_depth_cap_prevents_runaway_tree():
    """Anti-Runaway Safeguard: Verify recursive decomposition is capped at configured max_depth."""
    session_factory, engine = await setup_test_environment()
    try:
        # Configure max_depth = 3
        service = SubtaskService(session_factory, max_depth=3)

        # Depth 1 -> Depth 2 (Level 1 child)
        res_depth2 = await service.decompose(
            task_id="TASK_PARENT_SCAN",
            subtasks=[SubtaskSpec(title="Child Level 1")],
        )
        child1_id = res_depth2.created_subtasks[0].task_id
        assert res_depth2.decomposition_depth == 2

        # Depth 2 -> Depth 3 (Level 2 grandchild)
        res_depth3 = await service.decompose(
            task_id=child1_id,
            subtasks=[SubtaskSpec(title="Grandchild Level 2")],
        )
        grandchild_id = res_depth3.created_subtasks[0].task_id
        assert res_depth3.decomposition_depth == 3

        # Depth 3 -> Depth 4 (Attempt beyond max_depth 3) -> Must raise DecompositionDepthExceededError
        with pytest.raises(DecompositionDepthExceededError) as exc_info:
            await service.decompose(
                task_id=grandchild_id,
                subtasks=[SubtaskSpec(title="Great-Grandchild Level 3 (Runaway)")],
            )

        assert "exceeds maximum allowed depth of 3" in str(exc_info.value)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_subtask_count_exceeded_rejection():
    """Verify creating more subtasks than max_subtasks threshold is rejected."""
    session_factory, engine = await setup_test_environment()
    try:
        service = SubtaskService(session_factory, max_subtasks=5)

        too_many_subtasks = [SubtaskSpec(title=f"Subtask {i}") for i in range(6)]

        with pytest.raises(SubtaskCountExceededError) as exc_info:
            await service.decompose(
                task_id="TASK_PARENT_SCAN",
                subtasks=too_many_subtasks,
            )

        assert "exceeds maximum allowed subtasks" in str(exc_info.value)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_decomposition_nonexistent_and_terminal_rejections():
    """Verify attempting to decompose nonexistent or already terminal tasks is cleanly rejected."""
    session_factory, engine = await setup_test_environment()
    try:
        service = SubtaskService(session_factory)

        # 1. Nonexistent task
        with pytest.raises(ParentTaskNotFoundError):
            await service.decompose(
                task_id="TASK_DOES_NOT_EXIST",
                subtasks=[SubtaskSpec(title="Child")],
            )

        # 2. Terminal completed task
        async with UnitOfWork(session_factory) as uow:
            await uow.tasks.update_status("TASK_PARENT_SCAN", TaskStatus.COMPLETED)
            await uow.commit()

        with pytest.raises(ParentTaskTerminalError) as exc_info:
            await service.decompose(
                task_id="TASK_PARENT_SCAN",
                subtasks=[SubtaskSpec(title="Child")],
            )

        assert "already in terminal state" in str(exc_info.value)
    finally:
        await engine.dispose()
