"""Priority Queue Task Scheduler with pluggable scoring, starvation-prevention aging, and department backpressure."""

import asyncio
import heapq
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.orchestrator.core import global_orchestrator
from app.orchestrator.models import OrchestratorEvent

logger = get_logger("scheduling.scheduler")

DEFAULT_MAX_QUEUE_DEPTH_PER_DEPARTMENT = 50
DEFAULT_AGING_RATE_PER_SECOND = 1.0  # 1.0 score boost per second of wait time


class SchedulerError(Exception):
    """Base exception for scheduler operations."""

    pass


class DepartmentBackpressureError(SchedulerError):
    """Raised when enqueuing a task into a department queue that has reached capacity limits."""

    def __init__(self, department_id: str, current_depth: int, max_depth: int) -> None:
        self.department_id = department_id
        self.current_depth = current_depth
        self.max_depth = max_depth
        super().__init__(
            f"Department '{department_id}' task queue is saturated: "
            f"{current_depth}/{max_depth} ready tasks enqueued (backpressure active)."
        )


class ScheduledTaskItem(BaseModel):
    """In-memory item representing a READY task waiting in the priority scheduler queue."""

    task_id: str
    engagement_id: str
    department_id: str
    assigned_role: str
    priority: int = Field(
        default=2, ge=1, le=4, description="Explicit priority: 1=LOW to 4=CRITICAL"
    )
    risk_score: float = Field(default=0.0, ge=0.0, description="Risk/severity score boost factor")
    enqueued_at: float = Field(
        default_factory=time.time, description="Monotonic enqueue timestamp in epoch seconds"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def age_seconds(self) -> float:
        """Calculate wait time in seconds since the task was enqueued."""
        return max(0.0, time.time() - self.enqueued_at)


# ==============================================================================
# Pluggable Scoring Strategy Pattern (Technical Decision)
# ==============================================================================


class PriorityScoringStrategy(ABC):
    """Abstract strategy protocol for calculating dynamic scheduling priority scores."""

    @abstractmethod
    def calculate_score(self, item: ScheduledTaskItem, current_time: float) -> float:
        """Compute the dynamic priority score. Higher score = higher dequeue priority."""
        pass


class DefaultPriorityScoringStrategy(PriorityScoringStrategy):
    """Standard scoring combining explicit priority, starvation-prevention aging, and risk weights.

    Formula:
        Score = (priority * 100.0) + (age_seconds * aging_rate) + (risk_score * 10.0)
    """

    def __init__(self, aging_rate: float = DEFAULT_AGING_RATE_PER_SECOND) -> None:
        self.aging_rate = aging_rate

    def calculate_score(self, item: ScheduledTaskItem, current_time: float) -> float:
        age_seconds = max(0.0, current_time - item.enqueued_at)
        explicit_component = item.priority * 100.0
        aging_component = age_seconds * self.aging_rate
        risk_component = item.risk_score * 10.0
        return explicit_component + aging_component + risk_component


class StrictPriorityScoringStrategy(PriorityScoringStrategy):
    """Scoring strategy strictly enforcing static priority without aging (for debugging/testing)."""

    def calculate_score(self, item: ScheduledTaskItem, current_time: float) -> float:
        return float(item.priority * 100.0)


class SchedulerStats(BaseModel):
    """Runtime statistics and queue metrics for the priority scheduler."""

    total_queued: int
    department_queue_depths: dict[str, int]
    oldest_task_age_seconds: float
    highest_priority_score: float
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


# ==============================================================================
# Priority Queue Scheduler
# ==============================================================================


class PriorityScheduler:
    """Heap-based priority task scheduler with pluggable scoring, aging starvation prevention, and backpressure."""

    def __init__(
        self,
        scoring_strategy: PriorityScoringStrategy | None = None,
        max_queue_depth_per_department: int = DEFAULT_MAX_QUEUE_DEPTH_PER_DEPARTMENT,
    ) -> None:
        self.scoring_strategy: PriorityScoringStrategy = (
            scoring_strategy or DefaultPriorityScoringStrategy()
        )
        self.max_queue_depth_per_department = max_queue_depth_per_department

        self._items: dict[str, ScheduledTaskItem] = {}
        self._department_items: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()
        self._is_listening: bool = False

    @property
    def total_queued(self) -> int:
        return len(self._items)

    def get_department_queue_depth(self, department_id: str) -> int:
        """Return current count of tasks queued for a specific department."""
        return len(self._department_items.get(department_id, set()))

    def is_department_saturated(self, department_id: str) -> bool:
        """Check if a department queue has reached the backpressure depth limit."""
        return self.get_department_queue_depth(department_id) >= self.max_queue_depth_per_department

    async def enqueue(self, item: ScheduledTaskItem) -> bool:
        """Add a READY task into the scheduler priority queue subject to department backpressure limits."""
        async with self._lock:
            # 1. Check if already present (idempotent update)
            if item.task_id in self._items:
                self._items[item.task_id] = item
                return True

            # 2. Check department backpressure capacity
            dept_id = item.department_id
            current_depth = len(self._department_items.get(dept_id, set()))
            if current_depth >= self.max_queue_depth_per_department:
                logger.warning(
                    f"Rejecting task '{item.task_id}': Department '{dept_id}' queue reached backpressure limit ({current_depth}/{self.max_queue_depth_per_department})",
                    department_id=dept_id,
                    task_id=item.task_id,
                    queue_depth=current_depth,
                )
                raise DepartmentBackpressureError(
                    department_id=dept_id,
                    current_depth=current_depth,
                    max_depth=self.max_queue_depth_per_department,
                )

            # 3. Store task item and update indexes
            self._items[item.task_id] = item
            if dept_id not in self._department_items:
                self._department_items[dept_id] = set()
            self._department_items[dept_id].add(item.task_id)

            logger.debug(
                f"Enqueued task '{item.task_id}' in priority scheduler (Priority {item.priority}, Dept: {dept_id})",
                task_id=item.task_id,
                priority=item.priority,
                department_id=dept_id,
            )
            return True

    async def dequeue(self, department_id: str | None = None) -> ScheduledTaskItem | None:
        """Dequeue the highest-priority ready task (dynamically re-scored with current timestamp).

        If department_id is provided, dequeues the highest-scoring task within that department.
        """
        async with self._lock:
            if not self._items:
                return None

            current_time = time.time()
            candidates: list[ScheduledTaskItem]

            if department_id:
                task_ids = self._department_items.get(department_id, set())
                candidates = [self._items[tid] for tid in task_ids if tid in self._items]
            else:
                candidates = list(self._items.values())

            if not candidates:
                return None

            # Build min-heap of (-score, enqueued_at, task_id, item)
            heap: list[tuple[float, float, str, ScheduledTaskItem]] = []
            for item in candidates:
                score = self.scoring_strategy.calculate_score(item, current_time)
                # Max-priority: lowest negative score pops first; ties broken by arrival time (earliest first)
                heapq.heappush(heap, (-score, item.enqueued_at, item.task_id, item))

            _, _, popped_task_id, popped_item = heapq.heappop(heap)

            # Remove from internal registry and department index
            del self._items[popped_task_id]
            dept = popped_item.department_id
            if dept in self._department_items:
                self._department_items[dept].discard(popped_task_id)
                if not self._department_items[dept]:
                    del self._department_items[dept]

            logger.debug(
                f"Dequeued task '{popped_task_id}' with dynamic priority score (Dept: {dept})",
                task_id=popped_task_id,
                department_id=dept,
            )
            return popped_item

    async def peek(self, department_id: str | None = None) -> ScheduledTaskItem | None:
        """Inspect the highest-priority ready task without removing it from the queue."""
        async with self._lock:
            if not self._items:
                return None

            current_time = time.time()
            candidates = (
                [
                    self._items[tid]
                    for tid in self._department_items.get(department_id, set())
                    if tid in self._items
                ]
                if department_id
                else list(self._items.values())
            )

            if not candidates:
                return None

            best_item: ScheduledTaskItem | None = None
            best_score = float("-inf")

            for item in candidates:
                score = self.scoring_strategy.calculate_score(item, current_time)
                if score > best_score:
                    best_score = score
                    best_item = item

            return best_item

    async def remove(self, task_id: str) -> bool:
        """Remove a task from the scheduler queue (e.g. if cancelled or assigned externally)."""
        async with self._lock:
            item = self._items.pop(task_id, None)
            if not item:
                return False

            dept = item.department_id
            if dept in self._department_items:
                self._department_items[dept].discard(task_id)
                if not self._department_items[dept]:
                    del self._department_items[dept]

            logger.debug(f"Removed task '{task_id}' from scheduler queue", task_id=task_id)
            return True

    async def list_queued(self, department_id: str | None = None) -> list[ScheduledTaskItem]:
        """List all currently queued tasks ordered by dynamic priority score."""
        async with self._lock:
            current_time = time.time()
            candidates = (
                [
                    self._items[tid]
                    for tid in self._department_items.get(department_id, set())
                    if tid in self._items
                ]
                if department_id
                else list(self._items.values())
            )

            return sorted(
                candidates,
                key=lambda item: self.scoring_strategy.calculate_score(item, current_time),
                reverse=True,
            )

    async def get_stats(self) -> SchedulerStats:
        """Compute live queue statistics and starvation metrics."""
        async with self._lock:
            current_time = time.time()
            total = len(self._items)
            dept_depths = {dept: len(tids) for dept, tids in self._department_items.items()}

            if not self._items:
                return SchedulerStats(
                    total_queued=0,
                    department_queue_depths={},
                    oldest_task_age_seconds=0.0,
                    highest_priority_score=0.0,
                )

            oldest_age = max(current_time - item.enqueued_at for item in self._items.values())
            highest_score = max(
                self.scoring_strategy.calculate_score(item, current_time)
                for item in self._items.values()
            )

            return SchedulerStats(
                total_queued=total,
                department_queue_depths=dept_depths,
                oldest_task_age_seconds=round(oldest_age, 2),
                highest_priority_score=round(highest_score, 2),
            )

    async def clear(self) -> None:
        """Clear all tasks from the scheduler queue (primarily for test resets)."""
        async with self._lock:
            self._items.clear()
            self._department_items.clear()

    # ==========================================================================
    # Orchestrator TaskReady Event Consumer
    # ==========================================================================

    def start_event_listener(self) -> None:
        """Subscribe scheduler to orchestrator TaskReady events."""
        if not self._is_listening:
            global_orchestrator.register_event_subscriber(self._handle_orchestrator_event)
            self._is_listening = True
            logger.info("PriorityScheduler subscribed to orchestrator task_ready events")

    def stop_event_listener(self) -> None:
        """Unsubscribe scheduler from orchestrator event stream."""
        if self._is_listening:
            global_orchestrator.unregister_event_subscriber(self._handle_orchestrator_event)
            self._is_listening = False
            logger.info("PriorityScheduler unsubscribed from orchestrator events")

    async def _handle_orchestrator_event(self, event: OrchestratorEvent) -> None:
        """Consume TaskReady events and automatically enqueue tasks into the priority queue."""
        if event.event_type == "task_ready":
            payload = event.payload or {}
            task_id = str(payload.get("task_id") or event.task_id or "")
            engagement_id = str(payload.get("engagement_id") or event.engagement_id or "default")
            department_id = str(payload.get("department_id") or event.department_id or "dept_recon")
            assigned_role = str(payload.get("assigned_role") or "role_web_discovery")
            priority = int(payload.get("priority", 2))

            if not task_id:
                return

            item = ScheduledTaskItem(
                task_id=task_id,
                engagement_id=engagement_id,
                department_id=department_id,
                assigned_role=assigned_role,
                priority=priority,
                enqueued_at=time.time(),
                metadata=payload,
            )

            try:
                await self.enqueue(item)
            except DepartmentBackpressureError as bp_err:
                logger.error(f"Failed to auto-enqueue task '{task_id}': {bp_err}")


# Global singleton instance of the priority scheduler
global_priority_scheduler = PriorityScheduler()
