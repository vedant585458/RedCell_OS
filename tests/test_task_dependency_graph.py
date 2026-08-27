"""Unit and integration tests for TaskDependencyGraph, incremental DFS cycle detection, and topological readiness computation."""

import pytest
from app.domain.engagement import Base, EngagementCreateRequest
from app.domain.task import TaskCreateRequest, TaskStatus
from app.repositories.unit_of_work import UnitOfWork
from app.services.org_bootstrap import OrgBootstrapService
from app.tasks.dependency_graph import (
    CyclicDependencyError,
    SelfDependencyError,
    TaskDependencyGraph,
    TaskDependencyGraphEngine,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def test_linear_chain_dependency_and_readiness_cascade():
    """Unit Test: Linear Chain A -> B -> C (B depends on A, C depends on B)."""
    graph = TaskDependencyGraph()
    graph.add_node("task-A", TaskStatus.READY)
    graph.add_node("task-B", TaskStatus.PENDING)
    graph.add_node("task-C", TaskStatus.PENDING)

    # Edge: B depends on A, C depends on B
    graph.add_edge("task-B", "task-A")
    graph.add_edge("task-C", "task-B")

    # 1. Topological order & Execution Waves
    assert graph.get_topological_order() == ["task-A", "task-B", "task-C"]
    assert graph.get_execution_waves() == [["task-A"], ["task-B"], ["task-C"]]

    # 2. Initial readiness
    assert graph.is_task_ready("task-A") is True
    assert graph.is_task_ready("task-B") is False
    assert graph.is_task_ready("task-C") is False

    # 3. Complete A -> B becomes unblocked
    unblocked_1 = graph.compute_unblocked_tasks("task-A")
    assert unblocked_1 == ["task-B"]
    assert graph.is_task_ready("task-B") is True
    assert graph.is_task_ready("task-C") is False

    # 4. Complete B -> C becomes unblocked
    unblocked_2 = graph.compute_unblocked_tasks("task-B")
    assert unblocked_2 == ["task-C"]
    assert graph.is_task_ready("task-C") is True


def test_diamond_dependency_graph():
    """Unit Test: Diamond dependency graph.

    A -> B, A -> C; B -> D, C -> D (D depends on both B and C).
    """
    graph = TaskDependencyGraph()
    for node in ["A", "B", "C", "D"]:
        graph.add_node(node, TaskStatus.PENDING)

    # A has no dependencies
    graph.set_status("A", TaskStatus.READY)

    # B and C depend on A
    graph.add_edge("B", "A")
    graph.add_edge("C", "A")

    # D depends on both B and C
    graph.add_edge("D", "B")
    graph.add_edge("D", "C")

    # Execution Waves: Wave 1 = [A], Wave 2 = [B, C], Wave 3 = [D]
    assert graph.get_execution_waves() == [["A"], ["B", "C"], ["D"]]

    # Complete A -> B and C become unblocked
    unblocked_A = graph.compute_unblocked_tasks("A")
    assert sorted(unblocked_A) == ["B", "C"]
    assert graph.is_task_ready("D") is False

    # Complete only B -> D should NOT be ready yet (waiting on C)
    unblocked_B = graph.compute_unblocked_tasks("B")
    assert unblocked_B == []
    assert graph.is_task_ready("D") is False

    # Complete C (last dependency) -> D flips to READY!
    unblocked_C = graph.compute_unblocked_tasks("C")
    assert unblocked_C == ["D"]
    assert graph.is_task_ready("D") is True


def test_attempted_cycle_detection_rejection():
    """Acceptance Criteria & Technical Decision: Adding an edge creating a cycle is synchronously rejected."""
    graph = TaskDependencyGraph()

    # Linear: B depends on A, C depends on B
    graph.add_edge("B", "A")
    graph.add_edge("C", "B")

    # 1. Attempt cycle: A depends on C (creates cycle A -> B -> C -> A)
    with pytest.raises(CyclicDependencyError) as exc_info:
        graph.add_edge("A", "C")

    assert "Cyclic dependency detected" in str(exc_info.value)
    assert exc_info.value.from_task == "A"
    assert exc_info.value.to_task == "C"

    # 2. Attempt self-dependency: A depends on A
    with pytest.raises(SelfDependencyError) as exc_self:
        graph.add_edge("A", "A")

    assert "cannot depend on itself" in str(exc_self.value)


def test_wide_fan_in_dependency_readiness():
    """Unit Test: Wide Fan-In graph with 5 prerequisites converging into 1 final task."""
    graph = TaskDependencyGraph()
    prereqs = [f"recon-0{i}" for i in range(1, 6)]
    final_task = "consolidated-report"

    graph.add_node(final_task, TaskStatus.PENDING)
    for p in prereqs:
        graph.add_node(p, TaskStatus.READY)
        graph.add_edge(final_task, p)

    # Complete 4 out of 5 prerequisites
    for p in prereqs[:4]:
        unblocked = graph.compute_unblocked_tasks(p)
        assert unblocked == []
        assert graph.is_task_ready(final_task) is False

    # Complete the 5th and final prerequisite -> final_task flips to READY!
    unblocked_final = graph.compute_unblocked_tasks(prereqs[4])
    assert unblocked_final == [final_task]
    assert graph.is_task_ready(final_task) is True


# ==============================================================================
# Database Integration Tests with TaskDependencyGraphEngine
# ==============================================================================


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
                engagement_id="eng-graph-test",
                title="Graph Engine Test Engagement",
                organization="CyberRange Corp",
                authorized_by="CISO",
            )
        )
        # Task 1 (Root recon)
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_T1",
                engagement_id="eng-graph-test",
                department_id="dept_recon",
                title="Network Discovery",
                assigned_role="role_network_mapper",
            )
        )
        await uow.tasks.update_status("TASK_T1", TaskStatus.READY)

        # Task 2 (Depends on Task 1)
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_T2",
                engagement_id="eng-graph-test",
                department_id="dept_recon",
                title="Port Scanning",
                assigned_role="role_network_mapper",
                depends_on=["TASK_T1"],
            )
        )

        # Task 3 (Depends on Task 2)
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_T3",
                engagement_id="eng-graph-test",
                department_id="dept_vuln_assessment",
                title="Vulnerability Scanning",
                assigned_role="role_vulnerability_scanner",
                depends_on=["TASK_T2"],
            )
        )
        await uow.commit()

    return session_factory, engine


@pytest.mark.asyncio
async def test_graph_engine_load_and_on_task_completed_unblocking():
    """Integration Test: Verify TaskDependencyGraphEngine loads from DB and updates unblocked tasks."""
    session_factory, engine = await setup_test_environment()
    try:
        graph_engine = TaskDependencyGraphEngine(session_factory)

        # 1. Verify loaded graph from DB
        graph = await graph_engine.load_engagement_graph("eng-graph-test")
        assert graph.get_topological_order() == ["TASK_T1", "TASK_T2", "TASK_T3"]

        # 2. Complete Task 1 -> Task 2 unblocked in DB to READY
        unblocked = await graph_engine.on_task_completed("TASK_T1", "eng-graph-test")
        assert unblocked == ["TASK_T2"]

        async with UnitOfWork(session_factory) as uow:
            t2 = await uow.tasks.get_by_id("TASK_T2")
            assert t2 is not None
            assert t2.status == TaskStatus.READY
            t3 = await uow.tasks.get_by_id("TASK_T3")
            assert t3 is not None
            assert t3.status == TaskStatus.PENDING

        # 3. Complete Task 2 -> Task 3 unblocked in DB to READY
        unblocked_2 = await graph_engine.on_task_completed("TASK_T2", "eng-graph-test")
        assert unblocked_2 == ["TASK_T3"]

        async with UnitOfWork(session_factory) as uow:
            t3_updated = await uow.tasks.get_by_id("TASK_T3")
            assert t3_updated is not None
            assert t3_updated.status == TaskStatus.READY
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_graph_engine_validate_and_reject_cyclic_edge():
    """Integration Test: Verify validate_and_add_dependency rejects cyclic edge before DB commit."""
    session_factory, engine = await setup_test_environment()
    try:
        graph_engine = TaskDependencyGraphEngine(session_factory)

        # Current DB DAG: TASK_T1 -> TASK_T2 -> TASK_T3
        # Attempting: TASK_T1 depends on TASK_T3 (cycle: T1 -> T2 -> T3 -> T1)
        with pytest.raises(CyclicDependencyError) as exc_info:
            await graph_engine.validate_and_add_dependency(
                task_id="TASK_T1",
                depends_on_task_id="TASK_T3",
                engagement_id="eng-graph-test",
            )

        assert "Cyclic dependency detected" in str(exc_info.value)

        # Verify DB edges table remains uncorrupted
        async with UnitOfWork(session_factory) as uow:
            t1 = await uow.tasks.get_task_response("TASK_T1")
            assert t1 is not None
            assert "TASK_T3" not in t1.depends_on
    finally:
        await engine.dispose()
