"""Execution package managing mediated command execution, Scope/ROE enforcement, and telemetry recording."""

from .service import (
    CommandExecutionService,
    ExecutionServiceError,
    MediatedExecutionResult,
    ScopeViolationError,
    SecurityPermissionDeniedError,
    global_command_execution_service,
    validate_target_against_scope,
)

__all__ = [
    "CommandExecutionService",
    "MediatedExecutionResult",
    "ExecutionServiceError",
    "ScopeViolationError",
    "SecurityPermissionDeniedError",
    "validate_target_against_scope",
    "global_command_execution_service",
]
