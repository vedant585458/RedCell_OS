"""Process execution, worker spawning, and active process registry package for RedCell_OS."""

from .registry import ProcessRecord, ProcessRegistry, global_process_registry
from .worker import ProcessResult, WorkerProcess

__all__ = [
    "WorkerProcess",
    "ProcessResult",
    "ProcessRecord",
    "ProcessRegistry",
    "global_process_registry",
]
