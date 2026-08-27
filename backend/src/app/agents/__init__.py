"""Agents package managing AI Employee execution, state machines, and lifecycles."""

from .events import (
    AgentLifecycleService,
    AgentStateChangedEventPayload,
)
from .state_machine import (
    ALLOWED_TRANSITIONS,
    AgentLifecycleState,
    AgentStateMachine,
    InvalidStateTransitionError,
    StateTransitionRecord,
)

__all__ = [
    "AgentLifecycleState",
    "InvalidStateTransitionError",
    "ALLOWED_TRANSITIONS",
    "StateTransitionRecord",
    "AgentStateMachine",
    "AgentStateChangedEventPayload",
    "AgentLifecycleService",
]
