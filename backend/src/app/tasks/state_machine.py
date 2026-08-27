"""Explicit Finite-State Machine (FSM) for Task lifecycles within Engagement DAGs."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger

logger = get_logger("tasks.fsm")


class TaskLifecycleState(StrEnum):
    """Lifecycle states for individual penetration testing tasks within an engagement DAG."""

    PENDING = "pending"  # Waiting on prerequisite upstream DAG dependencies
    READY = "ready"  # Upstream dependencies met; eligible for agent dispatch
    ASSIGNED = "assigned"  # Assigned to specialist AI Employee / role
    IN_PROGRESS = "in_progress"  # Actively executing tool subprocess or investigation
    BLOCKED = "blocked"  # Paused on operator approval gate or external condition
    REVIEW = "review"  # Deliverable or finding undergoing CISO quality review
    COMPLETED = "completed"  # Successfully finished and verified
    FAILED = "failed"  # Execution failed or exhausted recovery retries
    CANCELLED = "cancelled"  # Aborted by operator or engagement cancellation

    @classmethod
    def _missing_(cls, value: object) -> Any:
        """Allow case-insensitive lookups and common aliases (e.g. 'RUNNING' -> IN_PROGRESS)."""
        if isinstance(value, str):
            val_norm = value.lower().strip()
            aliases = {
                "running": cls.IN_PROGRESS,
                "in_progress": cls.IN_PROGRESS,
                "executing": cls.IN_PROGRESS,
                "awaiting_approval": cls.BLOCKED,
                "waiting_blocked": cls.BLOCKED,
                "blocked": cls.BLOCKED,
                "pending": cls.PENDING,
                "ready": cls.READY,
                "assigned": cls.ASSIGNED,
                "review": cls.REVIEW,
                "completed": cls.COMPLETED,
                "failed": cls.FAILED,
                "cancelled": cls.CANCELLED,
                "canceled": cls.CANCELLED,
            }
            if val_norm in aliases:
                return aliases[val_norm]
        return None


class InvalidTaskStateTransitionError(ValueError):
    """Raised when an illegal or unauthorized task state transition is attempted."""

    def __init__(
        self,
        from_state: TaskLifecycleState,
        to_state: TaskLifecycleState,
        task_id: str,
        reason: str = "",
    ) -> None:
        self.from_state = from_state
        self.to_state = to_state
        self.task_id = task_id
        self.reason = reason
        msg = f"Invalid Task FSM transition for task '{task_id}': cannot transition from '{from_state}' to '{to_state}'."
        if reason:
            msg += f" Reason: {reason}"
        super().__init__(msg)


# Centralized transition table defining strictly permitted task state transitions
ALLOWED_TASK_TRANSITIONS: dict[TaskLifecycleState, set[TaskLifecycleState]] = {
    TaskLifecycleState.PENDING: {
        TaskLifecycleState.READY,
        TaskLifecycleState.BLOCKED,
        TaskLifecycleState.CANCELLED,
    },
    TaskLifecycleState.READY: {
        TaskLifecycleState.ASSIGNED,
        TaskLifecycleState.IN_PROGRESS,
        TaskLifecycleState.BLOCKED,
        TaskLifecycleState.PENDING,
        TaskLifecycleState.CANCELLED,
    },
    TaskLifecycleState.ASSIGNED: {
        TaskLifecycleState.IN_PROGRESS,
        TaskLifecycleState.READY,
        TaskLifecycleState.BLOCKED,
        TaskLifecycleState.FAILED,
        TaskLifecycleState.CANCELLED,
    },
    TaskLifecycleState.IN_PROGRESS: {
        TaskLifecycleState.REVIEW,
        TaskLifecycleState.COMPLETED,
        TaskLifecycleState.BLOCKED,
        TaskLifecycleState.FAILED,
        TaskLifecycleState.READY,
        TaskLifecycleState.CANCELLED,
    },
    TaskLifecycleState.BLOCKED: {
        TaskLifecycleState.IN_PROGRESS,
        TaskLifecycleState.READY,
        TaskLifecycleState.ASSIGNED,
        TaskLifecycleState.FAILED,
        TaskLifecycleState.CANCELLED,
    },
    TaskLifecycleState.REVIEW: {
        TaskLifecycleState.COMPLETED,
        TaskLifecycleState.IN_PROGRESS,
        TaskLifecycleState.READY,
        TaskLifecycleState.FAILED,
        TaskLifecycleState.CANCELLED,
    },
    TaskLifecycleState.COMPLETED: {
        TaskLifecycleState.READY,  # Re-run / invalidation
        TaskLifecycleState.IN_PROGRESS,
    },
    TaskLifecycleState.FAILED: {
        TaskLifecycleState.READY,  # Re-attempt on tactical replan
        TaskLifecycleState.PENDING,  # DAG re-architecture
        TaskLifecycleState.CANCELLED,
    },
    TaskLifecycleState.CANCELLED: {
        TaskLifecycleState.PENDING,
        TaskLifecycleState.READY,
    },
}


class TaskStateTransitionRecord(BaseModel):
    """Immutable record capturing a discrete task state transition."""

    task_id: str
    from_state: TaskLifecycleState
    to_state: TaskLifecycleState
    trigger: str = Field(default="")
    correlation_id: str = Field(default="")
    assigned_agent_id: str | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


TaskTransitionCallback = (
    Callable[[TaskStateTransitionRecord], Awaitable[None]]
    | Callable[[TaskStateTransitionRecord], None]
)


class TaskStateMachine:
    """Explicit FSM engine validating task lifecycle transitions and computing DAG readiness."""

    def __init__(
        self,
        task_id: str,
        initial_state: TaskLifecycleState = TaskLifecycleState.PENDING,
        assigned_agent_id: str | None = None,
        on_transition: TaskTransitionCallback | None = None,
    ) -> None:
        self.task_id = task_id
        self.current_state = initial_state
        self.assigned_agent_id = assigned_agent_id
        self.on_transition = on_transition
        self.history: list[TaskStateTransitionRecord] = []

    def can_transition_to(self, target_state: TaskLifecycleState | str) -> bool:
        """Check if transitioning from current state to target state is legally permitted."""
        resolved_target = (
            target_state
            if isinstance(target_state, TaskLifecycleState)
            else TaskLifecycleState(target_state)
        )
        allowed_targets = ALLOWED_TASK_TRANSITIONS.get(self.current_state, set())
        return resolved_target in allowed_targets

    def transition_to(
        self,
        target_state: TaskLifecycleState | str,
        trigger: str = "",
        correlation_id: str = "",
        assigned_agent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskStateTransitionRecord:
        """Execute a validated task state transition, raising InvalidTaskStateTransitionError on illegal jumps."""
        resolved_target = (
            target_state
            if isinstance(target_state, TaskLifecycleState)
            else TaskLifecycleState(target_state)
        )

        if not self.can_transition_to(resolved_target):
            logger.error(
                "Illegal Task FSM transition attempted",
                task_id=self.task_id,
                from_state=self.current_state.value,
                to_state=resolved_target.value,
                trigger=trigger,
            )
            raise InvalidTaskStateTransitionError(
                from_state=self.current_state,
                to_state=resolved_target,
                task_id=self.task_id,
                reason=(
                    f"Transition not allowed in transition table. Valid targets from "
                    f"'{self.current_state.value}' are: {[s.value for s in ALLOWED_TASK_TRANSITIONS.get(self.current_state, set())]}"
                ),
            )

        from_state = self.current_state
        self.current_state = resolved_target

        if assigned_agent_id is not None:
            self.assigned_agent_id = assigned_agent_id

        record = TaskStateTransitionRecord(
            task_id=self.task_id,
            from_state=from_state,
            to_state=resolved_target,
            trigger=trigger,
            correlation_id=correlation_id,
            assigned_agent_id=self.assigned_agent_id,
            metadata=metadata or {},
        )
        self.history.append(record)

        logger.debug(
            "Task FSM transition succeeded",
            task_id=self.task_id,
            from_state=from_state.value,
            to_state=resolved_target.value,
            trigger=trigger,
        )

        if self.on_transition:
            try:
                res = self.on_transition(record)
                if hasattr(res, "__await__"):
                    import asyncio

                    asyncio.create_task(res)  # type: ignore[arg-type]
            except Exception as err:
                logger.warning(f"Error in task on_transition callback: {err}")

        return record

    def evaluate_readiness(
        self,
        completed_task_ids: set[str],
        dependency_task_ids: list[str] | set[str],
        correlation_id: str = "",
    ) -> bool:
        """Technical Decision: Task 'ready' state computed from dependency graph, not set manually.

        If all prerequisite tasks are satisfied and task is in PENDING, transitions to READY.
        """
        dep_set = set(dependency_task_ids)
        is_ready = dep_set.issubset(completed_task_ids)

        if is_ready and self.current_state == TaskLifecycleState.PENDING:
            self.transition_to(
                TaskLifecycleState.READY,
                trigger="dependencies_satisfied",
                correlation_id=correlation_id,
                metadata={"dependencies": list(dep_set)},
            )
            return True
        return is_ready

    # High-level domain transition helpers
    def mark_ready(self, correlation_id: str = "") -> TaskStateTransitionRecord:
        """Advance task to READY state when dependencies are satisfied."""
        return self.transition_to(
            TaskLifecycleState.READY,
            trigger="dependencies_cleared",
            correlation_id=correlation_id,
        )

    def assign_agent(self, agent_id: str, correlation_id: str = "") -> TaskStateTransitionRecord:
        """Assign an active AI employee specialist to the task."""
        return self.transition_to(
            TaskLifecycleState.ASSIGNED,
            trigger="agent_assigned",
            correlation_id=correlation_id,
            assigned_agent_id=agent_id,
            metadata={"assigned_agent_id": agent_id},
        )

    def start_progress(self, correlation_id: str = "") -> TaskStateTransitionRecord:
        """Start active execution of the task."""
        return self.transition_to(
            TaskLifecycleState.IN_PROGRESS,
            trigger="execution_started",
            correlation_id=correlation_id,
        )

    def block(
        self, reason: str = "", gate_id: str = "", correlation_id: str = ""
    ) -> TaskStateTransitionRecord:
        """Block task on approval gate or external prerequisite."""
        return self.transition_to(
            TaskLifecycleState.BLOCKED,
            trigger="approval_required" if gate_id else "task_blocked",
            correlation_id=correlation_id,
            metadata={"reason": reason, "gate_id": gate_id},
        )

    def unblock(self, correlation_id: str = "") -> TaskStateTransitionRecord:
        """Unblock task after approval granted or resource becomes available."""
        return self.transition_to(
            TaskLifecycleState.IN_PROGRESS,
            trigger="approval_granted_or_unblocked",
            correlation_id=correlation_id,
        )

    def enter_review(self, correlation_id: str = "") -> TaskStateTransitionRecord:
        """Submit findings or deliverables for CISO review."""
        return self.transition_to(
            TaskLifecycleState.REVIEW,
            trigger="findings_submitted_for_review",
            correlation_id=correlation_id,
        )

    def mark_completed(self, correlation_id: str = "") -> TaskStateTransitionRecord:
        """Mark task as successfully completed."""
        return self.transition_to(
            TaskLifecycleState.COMPLETED,
            trigger="task_finished_success",
            correlation_id=correlation_id,
        )

    def mark_failed(self, reason: str = "", correlation_id: str = "") -> TaskStateTransitionRecord:
        """Mark task as failed after exhausting retries."""
        return self.transition_to(
            TaskLifecycleState.FAILED,
            trigger="execution_failed",
            correlation_id=correlation_id,
            metadata={"reason": reason},
        )

    def cancel(
        self, reason: str = "operator_cancelled", correlation_id: str = ""
    ) -> TaskStateTransitionRecord:
        """Cancel task execution."""
        return self.transition_to(
            TaskLifecycleState.CANCELLED,
            trigger=reason,
            correlation_id=correlation_id,
            metadata={"reason": reason},
        )
