"""Subprocess Execution Sandboxing with POSIX rlimits (CPU/RAM/File), CWD workspace jailing, and allowlist-based env scrubbing."""

import os
import sys
from collections.abc import Callable

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import get_logger
from app.process.worker import LineCallback, WorkerProcess

logger = get_logger("process.sandbox")

# Canonical Allowlist of Environment Variables (Technical Decision: Allowlist-based, not denylist)
CANONICAL_ENV_ALLOWLIST: set[str] = {
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "TMPDIR",
    "TEMP",
    "TMP",
    "PYTHONUNBUFFERED",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONPATH",
    "SHELL",
    "TZ",
}


class ResourceLimits(BaseModel):
    """Resource constraints applied to sandboxed worker subprocesses."""

    max_memory_mb: int = Field(
        default=1024, ge=16, le=16384, description="Virtual address space limit (RLIMIT_AS) in MB"
    )
    max_cpu_sec: int = Field(
        default=60, ge=1, le=3600, description="CPU time limit (RLIMIT_CPU) in seconds"
    )
    max_file_size_mb: int = Field(
        default=100, ge=1, le=4096, description="Maximum created file size (RLIMIT_FSIZE) in MB"
    )
    max_open_files: int = Field(
        default=256, ge=16, le=4096, description="Maximum open file descriptors (RLIMIT_NOFILE)"
    )
    timeout_sec: float = Field(
        default=120.0, ge=1.0, le=3600.0, description="Wall-clock execution timeout in seconds"
    )


def scrub_environment(
    workspace_path: str,
    extra_allowed_keys: set[str] | list[str] | None = None,
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Technical Decision: Scrub ambient environment variables using a strict allowlist.

    Drops all un-allowlisted environment variables (secrets, tokens, API keys, database credentials)
    to prevent secret leakage to agent-executed tool binaries.
    """
    effective_allowlist = CANONICAL_ENV_ALLOWLIST.union(extra_allowed_keys or [])
    scrubbed: dict[str, str] = {}

    for key, value in os.environ.items():
        if key in effective_allowlist:
            scrubbed[key] = value

    # Ensure safe system PATH
    user_local_bin = os.path.expanduser("~/.local/bin")
    current_path = scrubbed.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    if user_local_bin not in current_path:
        scrubbed["PATH"] = f"{user_local_bin}:{current_path}"

    # Set isolated temporary directory inside workspace
    workspace_tmp = os.path.join(workspace_path, "tmp")
    os.makedirs(workspace_tmp, exist_ok=True)
    scrubbed["TMPDIR"] = workspace_tmp
    scrubbed["TEMP"] = workspace_tmp
    scrubbed["TMP"] = workspace_tmp

    # Apply explicit parameter overrides if provided
    if overrides:
        scrubbed.update(overrides)

    return scrubbed


def validate_workspace_jail(workspace_path: str, cwd: str | None = None) -> str:
    """Validate that the working directory (cwd) is jailed strictly inside the agent workspace boundary."""
    canonical_ws = os.path.realpath(os.path.abspath(workspace_path))
    target_cwd = os.path.realpath(os.path.abspath(cwd or workspace_path))

    # Assert CWD is within workspace hierarchy
    if not (target_cwd == canonical_ws or target_cwd.startswith(canonical_ws + os.sep)):
        raise PermissionError(
            f"Security Sandbox Violation: Working directory '{target_cwd}' escapes workspace jail '{canonical_ws}'."
        )

    return target_cwd


def build_rlimit_preexec(limits: ResourceLimits) -> Callable[[], None] | None:
    """Construct POSIX preexec_fn applying RLIMIT_AS, RLIMIT_CPU, RLIMIT_FSIZE, and RLIMIT_NOFILE constraints."""
    if sys.platform == "win32":
        # Documented limitation: rlimits are Linux/POSIX specific
        return None

    def _apply_rlimits() -> None:
        try:
            import resource

            # 1. Memory limit (RLIMIT_AS: virtual address space)
            if limits.max_memory_mb > 0:
                mem_bytes = limits.max_memory_mb * 1024 * 1024
                try:
                    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
                except (ValueError, OSError):
                    pass

            # 2. CPU time limit (RLIMIT_CPU: sends SIGXCPU then SIGKILL)
            if limits.max_cpu_sec > 0:
                try:
                    resource.setrlimit(
                        resource.RLIMIT_CPU, (limits.max_cpu_sec, limits.max_cpu_sec)
                    )
                except (ValueError, OSError):
                    pass

            # 3. Max created file size (RLIMIT_FSIZE: sends SIGXFSZ on overflow)
            if limits.max_file_size_mb > 0:
                file_bytes = limits.max_file_size_mb * 1024 * 1024
                try:
                    resource.setrlimit(resource.RLIMIT_FSIZE, (file_bytes, file_bytes))
                except (ValueError, OSError):
                    pass

            # 4. Max open file descriptors (RLIMIT_NOFILE)
            if limits.max_open_files > 0:
                try:
                    resource.setrlimit(
                        resource.RLIMIT_NOFILE, (limits.max_open_files, limits.max_open_files)
                    )
                except (ValueError, OSError):
                    pass

        except Exception as e:
            # preexec_fn errors in child process
            sys.stderr.write(f"Warning: Failed to apply rlimits in child process: {e}\n")

    return _apply_rlimits


def create_sandboxed_worker(
    cmd: list[str],
    workspace_path: str,
    cwd: str | None = None,
    limits: ResourceLimits | None = None,
    env_overrides: dict[str, str] | None = None,
    extra_allowed_env: set[str] | list[str] | None = None,
    on_stdout_line: LineCallback | None = None,
    on_stderr_line: LineCallback | None = None,
) -> WorkerProcess:
    """Factory creating a hardened WorkerProcess with rlimits, CWD workspace jailing, and allowlist env scrubbing."""
    effective_limits = limits or ResourceLimits(
        max_memory_mb=settings.sandbox_ram_mb,
        max_cpu_sec=settings.sandbox_cpu_sec,
        timeout_sec=settings.sandbox_timeout_sec,
    )

    # 1. Validate workspace CWD jail
    jailed_cwd = validate_workspace_jail(workspace_path, cwd)

    # 2. Scrub environment variables (allowlist-based)
    clean_env = scrub_environment(
        workspace_path=workspace_path,
        extra_allowed_keys=extra_allowed_env,
        overrides=env_overrides,
    )

    # 3. Build POSIX rlimits preexec hook
    preexec = build_rlimit_preexec(effective_limits)

    logger.debug(
        "Instantiating sandboxed worker process",
        cmd=cmd,
        cwd=jailed_cwd,
        max_memory_mb=effective_limits.max_memory_mb,
        max_cpu_sec=effective_limits.max_cpu_sec,
        timeout_sec=effective_limits.timeout_sec,
    )

    return WorkerProcess(
        cmd=cmd,
        cwd=jailed_cwd,
        env=clean_env,
        timeout_sec=effective_limits.timeout_sec,
        on_stdout_line=on_stdout_line,
        on_stderr_line=on_stderr_line,
        preexec_fn=preexec,
    )
