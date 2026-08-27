"""Tasks package managing task models, state machines, DAG execution lifecycles, and recursive decomposition."""

from .decomposition import (
    DEFAULT_MAX_DECOMPOSITION_DEPTH,
    DEFAULT_MAX_SUBTASKS_PER_TASK,
    DecompositionDepthExceededError,
    DecompositionError,
    DecompositionRequest,
    DecompositionResult,
    ParentTaskNotFoundError,
    ParentTaskTerminalError,
    SubtaskCountExceededError,
    SubtaskService,
    SubtaskSpec,
)
from .state_machine import (
    ALLOWED_TASK_TRANSITIONS,
    InvalidTaskStateTransitionError,
    TaskLifecycleState,
    TaskStateMachine,
    TaskStateTransitionRecord,
)

__all__ = [
    "TaskLifecycleState",
    "InvalidTaskStateTransitionError",
    "ALLOWED_TASK_TRANSITIONS",
    "TaskStateTransitionRecord",
    "TaskStateMachine",
    "SubtaskSpec",
    "DecompositionRequest",
    "DecompositionResult",
    "SubtaskService",
    "DecompositionError",
    "DecompositionDepthExceededError",
    "SubtaskCountExceededError",
    "ParentTaskNotFoundError",
    "ParentTaskTerminalError",
    "DEFAULT_MAX_DECOMPOSITION_DEPTH",
    "DEFAULT_MAX_SUBTASKS_PER_TASK",
]
