"""Scheduling package managing priority queues, scoring strategies, task-agent assignment, and dispatch."""

from .assignment import (
    AssignmentError,
    AssignmentResult,
    AssignmentService,
    TaskAssignedEventPayload,
    global_assignment_service,
)
from .scheduler import (
    DEFAULT_AGING_RATE_PER_SECOND,
    DEFAULT_MAX_QUEUE_DEPTH_PER_DEPARTMENT,
    DefaultPriorityScoringStrategy,
    DepartmentBackpressureError,
    PriorityScheduler,
    PriorityScoringStrategy,
    ScheduledTaskItem,
    SchedulerError,
    SchedulerStats,
    StrictPriorityScoringStrategy,
    global_priority_scheduler,
)

__all__ = [
    "ScheduledTaskItem",
    "PriorityScoringStrategy",
    "DefaultPriorityScoringStrategy",
    "StrictPriorityScoringStrategy",
    "SchedulerStats",
    "PriorityScheduler",
    "SchedulerError",
    "DepartmentBackpressureError",
    "DEFAULT_MAX_QUEUE_DEPTH_PER_DEPARTMENT",
    "DEFAULT_AGING_RATE_PER_SECOND",
    "global_priority_scheduler",
    "AssignmentService",
    "AssignmentResult",
    "AssignmentError",
    "TaskAssignedEventPayload",
    "global_assignment_service",
]
