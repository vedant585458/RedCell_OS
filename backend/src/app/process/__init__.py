"""Process execution, worker spawning, sandboxing with rlimits, and active process registry package for RedCell_OS."""

from .registry import ProcessRecord, ProcessRegistry, global_process_registry
from .sandbox import (
    CANONICAL_ENV_ALLOWLIST,
    ResourceLimits,
    build_rlimit_preexec,
    create_sandboxed_worker,
    scrub_environment,
    validate_workspace_jail,
)
from .worker import ProcessResult, WorkerProcess

__all__ = [
    "WorkerProcess",
    "ProcessResult",
    "ProcessRecord",
    "ProcessRegistry",
    "global_process_registry",
    "ResourceLimits",
    "CANONICAL_ENV_ALLOWLIST",
    "scrub_environment",
    "validate_workspace_jail",
    "build_rlimit_preexec",
    "create_sandboxed_worker",
]
