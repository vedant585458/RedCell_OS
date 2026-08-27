"""Agents package managing AI Employee execution, state machines, lifecycles, working memory, long-term memories, and registries."""

from .context_builder import (
    DEFAULT_CONTEXT_TOKEN_BUDGET,
    AgentWorkingContext,
    ContextBuilder,
    RankedContextItem,
    estimate_tokens,
)
from .events import (
    AgentLifecycleService,
    AgentStateChangedEventPayload,
)
from .memory_service import (
    AgentMemoryService,
    MemoryPoisoningFilter,
)
from .recovery import (
    DEFAULT_POLICY_RULES,
    AgentRecoveryService,
    FailureClassification,
    FailureType,
    RecoveryAbandonedError,
    RecoveryAction,
    RecoveryDecision,
    RecoveryEscalatedError,
    RecoveryPolicy,
    RecoveryPolicyRule,
)
from .registry import (
    NON_TERMINAL_STATES,
    AgentReconciliationReport,
    AgentRegistry,
    AgentRuntimeHandle,
    global_agent_registry,
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
    "FailureClassification",
    "FailureType",
    "RecoveryAction",
    "RecoveryPolicyRule",
    "RecoveryDecision",
    "RecoveryEscalatedError",
    "RecoveryAbandonedError",
    "DEFAULT_POLICY_RULES",
    "RecoveryPolicy",
    "AgentRecoveryService",
    "AgentRuntimeHandle",
    "AgentReconciliationReport",
    "AgentRegistry",
    "global_agent_registry",
    "NON_TERMINAL_STATES",
    "ContextBuilder",
    "AgentWorkingContext",
    "RankedContextItem",
    "estimate_tokens",
    "DEFAULT_CONTEXT_TOKEN_BUDGET",
    "AgentMemoryService",
    "MemoryPoisoningFilter",
]
