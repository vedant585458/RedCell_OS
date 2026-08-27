"""Service for recursive task decomposition into subtasks, priority inheritance, and aggregate status derivation."""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.domain.audit import AuditEventCreateRequest
from app.domain.task import TaskCreateRequest, TaskResponse, TaskStatus
from app.orchestrator.core import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork

logger = get_logger("tasks.decomposition")

DEFAULT_MAX_DECOMPOSITION_DEPTH = 3
DEFAULT_MAX_SUBTASKS_PER_TASK = 20


class DecompositionError(ValueError):
    """Base exception for task decomposition errors."""

    pass


class DecompositionDepthExceededError(DecompositionError):
    """Raised when task decomposition exceeds the maximum allowed tree depth."""

    def __init__(self, task_id: str, current_depth: int, max_depth: int) -> None:
        self.task_id = task_id
        self.current_depth = current_depth
        self.max_depth = max_depth
        super().__init__(
            f"Cannot decompose task '{task_id}': recursion depth {current_depth} "
            f"exceeds maximum allowed depth of {max_depth}."
        )


class SubtaskCountExceededError(DecompositionError):
    """Raised when attempting to create more subtasks than the configured threshold."""

    def __init__(self, count: int, max_count: int) -> None:
        self.count = count
        self.max_count = max_count
        super().__init__(
            f"Subtask count {count} exceeds maximum allowed subtasks per decomposition ({max_count})."
        )


class ParentTaskNotFoundError(DecompositionError):
    """Raised when the specified parent task does not exist."""

    pass


class ParentTaskTerminalError(DecompositionError):
    """Raised when attempting to decompose a task that is already in a terminal state."""

    pass


class SubtaskSpec(BaseModel):
    """Specification for a child subtask created during decomposition."""

    title: str = Field(..., min_length=2, max_length=128)
    description: str = Field(default="")
    department_id: str | None = Field(
        default=None, description="Executing department; inherits from parent if omitted"
    )
    assigned_role: str | None = Field(
        default=None, description="Required specialist role; inherits from parent if omitted"
    )
    assigned_agent_id: str | None = Field(default=None)
    priority: int | None = Field(
        default=None,
        ge=1,
        le=4,
        description="Priority level (1-4); inherits from parent if omitted",
    )
    depends_on: list[str] = Field(
        default_factory=list, description="Prerequisite dependency task IDs"
    )
    requires_approval_gate: str | None = Field(default=None)
    input_context: dict[str, Any] = Field(default_factory=dict)


class DecompositionRequest(BaseModel):
    """Inbound request to decompose a parent task into subtasks."""

    task_id: str = Field(..., description="ID of parent task to decompose")
    subtasks: list[SubtaskSpec] = Field(..., min_length=1)
    actor_id: str = Field(default="agent-ciso-01")
    correlation_id: str = Field(default="")
    reason: str = Field(default="Tactical task decomposition into specialist subtasks")


class DecompositionResult(BaseModel):
    """Structured result returned upon successful task decomposition."""

    parent_task_id: str
    engagement_id: str
    created_subtasks: list[TaskResponse]
    parent_prior_status: str
    parent_new_status: str
    decomposition_depth: int
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class SubtaskService:
    """Service managing recursive task decomposition, priority inheritance, and derived parent statuses."""

    def __init__(
        self,
        session_factory: Any,
        max_depth: int = DEFAULT_MAX_DECOMPOSITION_DEPTH,
        max_subtasks: int = DEFAULT_MAX_SUBTASKS_PER_TASK,
    ) -> None:
        self.session_factory = session_factory
        self.max_depth = max_depth
        self.max_subtasks = max_subtasks

    async def get_task_depth(self, task_id: str, uow: UnitOfWork) -> int:
        """Calculate the tree depth of a task by walking parent pointers up to the root (Root = Depth 1)."""
        depth = 1
        current_id = task_id

        while True:
            task = await uow.tasks.get_by_id(current_id)
            if not task or not task.parent_task_id:
                break
            depth += 1
            current_id = task.parent_task_id
            if depth > 50:  # Safety circuit breaker against circular parent cycles
                break

        return depth

    async def decompose(
        self,
        task_id: str,
        subtasks: list[SubtaskSpec],
        actor_id: str = "agent-ciso-01",
        correlation_id: str = "",
        reason: str = "Tactical task decomposition",
    ) -> DecompositionResult:
        """Decompose a parent task into a set of child subtasks with priority inheritance and auto-blocking."""
        if not subtasks:
            raise DecompositionError("Cannot decompose task: subtask list must not be empty.")

        if len(subtasks) > self.max_subtasks:
            raise SubtaskCountExceededError(len(subtasks), self.max_subtasks)

        corr_id = correlation_id or f"corr-decomp-{task_id}-{uuid.uuid4().hex[:8]}"

        async with UnitOfWork(self.session_factory) as uow:
            # 1. Fetch and validate parent task
            parent_task = await uow.tasks.get_by_id(task_id)
            if not parent_task:
                raise ParentTaskNotFoundError(f"Parent task '{task_id}' not found.")

            if parent_task.status in (TaskStatus.COMPLETED.value, TaskStatus.CANCELLED.value):
                raise ParentTaskTerminalError(
                    f"Cannot decompose task '{task_id}': task is already in terminal state '{parent_task.status}'."
                )

            # 2. Check decomposition tree depth cap (Anti-runaway safeguard)
            parent_depth = await self.get_task_depth(task_id, uow)
            child_depth = parent_depth + 1
            if child_depth > self.max_depth:
                raise DecompositionDepthExceededError(task_id, child_depth, self.max_depth)

            parent_resp = parent_task.to_response()
            prior_parent_status = str(parent_task.status)
            created_subtasks: list[TaskResponse] = []

            # 3. Create linked subtasks with priority and attribute inheritance
            for idx, spec in enumerate(subtasks):
                # Priority Inheritance Rule: inherit parent's priority if not overridden
                effective_priority = (
                    spec.priority if spec.priority is not None else parent_task.priority
                )
                effective_dept = spec.department_id or parent_task.department_id
                effective_role = spec.assigned_role or parent_task.assigned_role

                subtask_id = f"{task_id}-sub-{idx + 1}-{uuid.uuid4().hex[:4]}"

                req = TaskCreateRequest(
                    task_id=subtask_id,
                    engagement_id=parent_task.engagement_id,
                    department_id=effective_dept,
                    title=spec.title,
                    description=spec.description,
                    priority=effective_priority,
                    assigned_role=effective_role,
                    assigned_agent_id=spec.assigned_agent_id,
                    parent_task_id=task_id,
                    depends_on=spec.depends_on,
                    requires_approval_gate=spec.requires_approval_gate,
                    input_context=spec.input_context or parent_resp.input_context,
                )

                created = await uow.tasks.create_task(req)

                # If subtask has no prerequisite dependencies, advance to READY immediately
                if not spec.depends_on:
                    await uow.tasks.update_status(created.task_id, TaskStatus.READY)
                    created.status = TaskStatus.READY

                created_subtasks.append(created)

            # 4. Auto-block parent task while subtasks exist and are active
            # Technical Decision: Parent task status derived from subtask aggregate
            new_parent_status = TaskStatus.BLOCKED.value
            await uow.tasks.update_status(task_id, new_parent_status)

            # 5. Record immutable audit event
            await uow.audit.append_audit_event(
                AuditEventCreateRequest(
                    event_id=f"aud-decomp-{task_id}-{uuid.uuid4().hex[:8]}",
                    engagement_id=parent_task.engagement_id,
                    correlation_id=corr_id,
                    event_type="task_decomposed",
                    actor_type="AGENT",
                    actor_id=actor_id,
                    payload={
                        "parent_task_id": task_id,
                        "engagement_id": parent_task.engagement_id,
                        "subtask_count": len(created_subtasks),
                        "subtask_ids": [t.task_id for t in created_subtasks],
                        "depth": child_depth,
                        "reason": reason,
                    },
                )
            )
            await uow.commit()

        # 6. Broadcast events over orchestrator bus
        await global_orchestrator.emit_event(
            event_type="task_decomposed",
            correlation_id=corr_id,
            engagement_id=parent_task.engagement_id,
            task_id=task_id,
            payload={
                "parent_task_id": task_id,
                "subtask_ids": [t.task_id for t in created_subtasks],
                "subtask_count": len(created_subtasks),
                "depth": child_depth,
            },
        )

        logger.info(
            f"Decomposed task '{task_id}' into {len(created_subtasks)} subtasks at depth {child_depth}",
            parent_task_id=task_id,
            subtask_count=len(created_subtasks),
            depth=child_depth,
        )

        return DecompositionResult(
            parent_task_id=task_id,
            engagement_id=parent_task.engagement_id,
            created_subtasks=created_subtasks,
            parent_prior_status=prior_parent_status,
            parent_new_status=new_parent_status,
            decomposition_depth=child_depth,
        )

    def derive_parent_status(self, subtasks: list[TaskResponse]) -> TaskStatus:
        """Technical Decision: Compute parent task lifecycle status from aggregate subtask states.

        - If all subtasks are COMPLETED -> COMPLETED
        - If all subtasks are CANCELLED -> CANCELLED
        - If any subtask is FAILED -> FAILED
        - If active/ready/pending subtasks remain -> BLOCKED (waiting on subtasks)
        """
        if not subtasks:
            return TaskStatus.PENDING

        statuses = [t.status for t in subtasks]

        if all(s == TaskStatus.COMPLETED for s in statuses):
            return TaskStatus.COMPLETED

        if all(s == TaskStatus.CANCELLED for s in statuses):
            return TaskStatus.CANCELLED

        if any(s == TaskStatus.FAILED for s in statuses):
            return TaskStatus.FAILED

        # Still executing or pending subtasks exist
        return TaskStatus.BLOCKED

    async def reconcile_parent_task(
        self,
        parent_task_id: str,
        correlation_id: str = "",
    ) -> TaskResponse | None:
        """Reconcile and update a parent task's status based on its subtasks.

        Recursively unblocks or completes parent hierarchy when subtasks complete.
        """
        corr_id = correlation_id or f"corr-rec-parent-{parent_task_id}-{uuid.uuid4().hex[:8]}"

        async with UnitOfWork(self.session_factory) as uow:
            parent = await uow.tasks.get_by_id(parent_task_id)
            if not parent:
                return None

            # Fetch all child subtasks
            subtasks = await uow.tasks.list_by_parent(parent_task_id)
            if not subtasks:
                return parent.to_response()

            derived_status = self.derive_parent_status(subtasks)

            # If derived status differs from current parent status, update it
            if parent.status != derived_status.value:
                prior = parent.status
                await uow.tasks.update_status(parent_task_id, derived_status)

                await uow.audit.append_audit_event(
                    AuditEventCreateRequest(
                        event_id=f"aud-par-status-{parent_task_id}-{uuid.uuid4().hex[:8]}",
                        engagement_id=parent.engagement_id,
                        correlation_id=corr_id,
                        event_type="parent_task_status_reconciled",
                        actor_type="SYSTEM",
                        actor_id="task-decomposition-service",
                        payload={
                            "parent_task_id": parent_task_id,
                            "prior_status": prior,
                            "new_status": derived_status.value,
                            "subtask_count": len(subtasks),
                        },
                    )
                )
                await uow.commit()

                # Emit status change event
                await global_orchestrator.emit_event(
                    event_type="task_status_changed",
                    correlation_id=corr_id,
                    engagement_id=parent.engagement_id,
                    task_id=parent_task_id,
                    payload={
                        "task_id": parent_task_id,
                        "prior_status": prior,
                        "new_status": derived_status.value,
                        "reason": f"Aggregate subtask status resolved to {derived_status.value}",
                    },
                )

                logger.info(
                    f"Parent task '{parent_task_id}' auto-reconciled {prior} -> {derived_status.value}",
                    parent_task_id=parent_task_id,
                    new_status=derived_status.value,
                )

                # Recursively reconcile grandparent task if present
                if parent.parent_task_id:
                    await self.reconcile_parent_task(parent.parent_task_id, corr_id)

            return await uow.tasks.get_task_response(parent_task_id)
