"""Unit and integration tests for PriorityScheduler, dynamic scoring, starvation-prevention aging, and department backpressure."""

import asyncio
import time

import pytest
from app.orchestrator import global_orchestrator
from app.scheduling.scheduler import (
    DefaultPriorityScoringStrategy,
    DepartmentBackpressureError,
    PriorityScheduler,
    PriorityScoringStrategy,
    ScheduledTaskItem,
    StrictPriorityScoringStrategy,
)


@pytest.mark.asyncio
async def test_priority_queue_ordering_acceptance_criteria():
    """Acceptance Criteria: Higher-priority ready tasks are dequeued before lower-priority ones."""
    scheduler = PriorityScheduler(scoring_strategy=StrictPriorityScoringStrategy())

    # Enqueue tasks with priorities 1 to 4
    tasks = [
        ScheduledTaskItem(
            task_id="task-low",
            engagement_id="eng-1",
            department_id="dept_recon",
            assigned_role="role_web_discovery",
            priority=1,
        ),
        ScheduledTaskItem(
            task_id="task-critical",
            engagement_id="eng-1",
            department_id="dept_recon",
            assigned_role="role_web_discovery",
            priority=4,
        ),
        ScheduledTaskItem(
            task_id="task-medium",
            engagement_id="eng-1",
            department_id="dept_recon",
            assigned_role="role_web_discovery",
            priority=2,
        ),
        ScheduledTaskItem(
            task_id="task-high",
            engagement_id="eng-1",
            department_id="dept_recon",
            assigned_role="role_web_discovery",
            priority=3,
        ),
    ]

    for t in tasks:
        await scheduler.enqueue(t)

    assert scheduler.total_queued == 4

    # Dequeue one by one and assert exact priority descending order
    d1 = await scheduler.dequeue()
    assert d1 is not None and d1.task_id == "task-critical" and d1.priority == 4

    d2 = await scheduler.dequeue()
    assert d2 is not None and d2.task_id == "task-high" and d2.priority == 3

    d3 = await scheduler.dequeue()
    assert d3 is not None and d3.task_id == "task-medium" and d3.priority == 2

    d4 = await scheduler.dequeue()
    assert d4 is not None and d4.task_id == "task-low" and d4.priority == 1

    assert await scheduler.dequeue() is None


@pytest.mark.asyncio
async def test_starvation_prevention_aging():
    """Risk Mitigation Test: Starvation-prevention aging allows an older low-priority task

    to eventually surpass a freshly queued high-priority task.
    """
    # Aging rate = 1.0 point per second
    strategy = DefaultPriorityScoringStrategy(aging_rate=1.0)
    scheduler = PriorityScheduler(scoring_strategy=strategy)

    now = time.time()

    # 1. Low Priority task enqueued 400 seconds ago (Base score = 100, Aging = +400 -> Total = 500)
    old_low_priority_task = ScheduledTaskItem(
        task_id="task-aged-low",
        engagement_id="eng-1",
        department_id="dept_recon",
        assigned_role="role_web_discovery",
        priority=1,
        enqueued_at=now - 400.0,
    )

    # 2. Critical task freshly enqueued 0 seconds ago (Base score = 400, Aging = 0 -> Total = 400)
    fresh_critical_task = ScheduledTaskItem(
        task_id="task-fresh-critical",
        engagement_id="eng-1",
        department_id="dept_recon",
        assigned_role="role_web_discovery",
        priority=4,
        enqueued_at=now,
    )

    await scheduler.enqueue(old_low_priority_task)
    await scheduler.enqueue(fresh_critical_task)

    # Dequeue: The aged task (score 500) must dequeue BEFORE the fresh critical task (score 400)
    first_popped = await scheduler.dequeue()
    assert first_popped is not None
    assert first_popped.task_id == "task-aged-low"

    second_popped = await scheduler.dequeue()
    assert second_popped is not None
    assert second_popped.task_id == "task-fresh-critical"


@pytest.mark.asyncio
async def test_department_scoped_dequeue():
    """Verify dequeue(department_id) pops highest priority task for the requested department only."""
    scheduler = PriorityScheduler(scoring_strategy=StrictPriorityScoringStrategy())

    await scheduler.enqueue(
        ScheduledTaskItem(
            task_id="recon-p4",
            engagement_id="eng-1",
            department_id="dept_recon",
            assigned_role="role_web_discovery",
            priority=4,
        )
    )
    await scheduler.enqueue(
        ScheduledTaskItem(
            task_id="vuln-p3",
            engagement_id="eng-1",
            department_id="dept_vuln_assessment",
            assigned_role="role_vulnerability_scanner",
            priority=3,
        )
    )
    await scheduler.enqueue(
        ScheduledTaskItem(
            task_id="vuln-p2",
            engagement_id="eng-1",
            department_id="dept_vuln_assessment",
            assigned_role="role_vulnerability_scanner",
            priority=2,
        )
    )

    # Request next task for dept_vuln_assessment -> Should pop vuln-p3, leaving recon-p4 intact
    vuln_task = await scheduler.dequeue(department_id="dept_vuln_assessment")
    assert vuln_task is not None
    assert vuln_task.task_id == "vuln-p3"

    # Recon task should still be in queue
    recon_task = await scheduler.dequeue(department_id="dept_recon")
    assert recon_task is not None
    assert recon_task.task_id == "recon-p4"


@pytest.mark.asyncio
async def test_pluggable_scoring_strategy_pattern():
    """Technical Decision: Verify custom pluggable scoring strategy determines scheduling order."""

    class ReversePriorityStrategy(PriorityScoringStrategy):
        """Custom strategy that prioritizes lower priority tasks first."""

        def calculate_score(
            self, item: ScheduledTaskItem, current_time: float
        ) -> float:
            return float((5 - item.priority) * 100.0)

    scheduler = PriorityScheduler(scoring_strategy=ReversePriorityStrategy())

    await scheduler.enqueue(
        ScheduledTaskItem(
            task_id="task-critical",
            engagement_id="e",
            department_id="d",
            assigned_role="r",
            priority=4,
        )
    )
    await scheduler.enqueue(
        ScheduledTaskItem(
            task_id="task-low",
            engagement_id="e",
            department_id="d",
            assigned_role="r",
            priority=1,
        )
    )

    # Under ReversePriorityStrategy, task-low (score 400) pops before task-critical (score 100)
    popped = await scheduler.dequeue()
    assert popped is not None
    assert popped.task_id == "task-low"


@pytest.mark.asyncio
async def test_department_backpressure_capacity_limits():
    """Verify department queue depth limit enforces backpressure and rejects overflow."""
    scheduler = PriorityScheduler(max_queue_depth_per_department=2)

    # Enqueue 2 tasks into dept_recon (reaches capacity 2/2)
    await scheduler.enqueue(
        ScheduledTaskItem(
            task_id="r1",
            engagement_id="e",
            department_id="dept_recon",
            assigned_role="r",
            priority=2,
        )
    )
    await scheduler.enqueue(
        ScheduledTaskItem(
            task_id="r2",
            engagement_id="e",
            department_id="dept_recon",
            assigned_role="r",
            priority=3,
        )
    )

    assert scheduler.get_department_queue_depth("dept_recon") == 2
    assert scheduler.is_department_saturated("dept_recon") is True

    # 3rd task to dept_recon must raise DepartmentBackpressureError
    with pytest.raises(DepartmentBackpressureError) as exc_info:
        await scheduler.enqueue(
            ScheduledTaskItem(
                task_id="r3",
                engagement_id="e",
                department_id="dept_recon",
                assigned_role="r",
                priority=4,
            )
        )

    assert "is saturated: 2/2" in str(exc_info.value)

    # Task to a different department (dept_exploit) must still succeed
    assert await scheduler.enqueue(
        ScheduledTaskItem(
            task_id="exp1",
            engagement_id="e",
            department_id="dept_exploit",
            assigned_role="r",
            priority=3,
        )
    )

    # Dequeue one from dept_recon -> allows r3 to be enqueued
    await scheduler.dequeue(department_id="dept_recon")
    assert await scheduler.enqueue(
        ScheduledTaskItem(
            task_id="r3",
            engagement_id="e",
            department_id="dept_recon",
            assigned_role="r",
            priority=4,
        )
    )


@pytest.mark.asyncio
async def test_task_ready_orchestrator_event_auto_enqueue():
    """Verify scheduler consumes TaskReady orchestrator events and enqueues tasks automatically."""
    scheduler = PriorityScheduler()
    scheduler.start_event_listener()
    await global_orchestrator.start()

    try:
        # Emit task_ready event
        await global_orchestrator.emit_event(
            event_type="task_ready",
            correlation_id="corr-sched-01",
            engagement_id="eng-sched-01",
            department_id="dept_recon",
            task_id="TASK_AUTO_ENQUEUE_01",
            payload={
                "task_id": "TASK_AUTO_ENQUEUE_01",
                "engagement_id": "eng-sched-01",
                "department_id": "dept_recon",
                "assigned_role": "role_web_discovery",
                "priority": 3,
            },
        )

        await asyncio.sleep(0.05)

        assert scheduler.total_queued == 1
        queued_item = await scheduler.peek()
        assert queued_item is not None
        assert queued_item.task_id == "TASK_AUTO_ENQUEUE_01"
        assert queued_item.priority == 3
        assert queued_item.department_id == "dept_recon"
    finally:
        scheduler.stop_event_listener()
        await global_orchestrator.stop()
