"""Unit and integration tests for Process Sandboxing with POSIX rlimits, workspace CWD jailing, and allowlist env scrubbing."""

import os
import sys
import tempfile

import pytest
from app.process.sandbox import (
    ResourceLimits,
    create_sandboxed_worker,
    scrub_environment,
    validate_workspace_jail,
)


@pytest.mark.asyncio
async def test_memory_bomb_killed_by_rlimit():
    """Acceptance Criteria: A command attempting to allocate memory exceeding max_memory_mb is terminated/killed."""
    if sys.platform == "win32":
        pytest.skip(
            "rlimits memory sandboxing is a Linux/POSIX specific security feature."
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        # Set a restrictive memory limit of 64 MB
        limits = ResourceLimits(max_memory_mb=64, timeout_sec=10.0)

        # Python script attempting to allocate 250 MB of memory
        memory_bomb_script = "x = bytearray(250 * 1024 * 1024)"

        worker = create_sandboxed_worker(
            cmd=["python3", "-c", memory_bomb_script],
            workspace_path=temp_dir,
            limits=limits,
        )

        result = await worker.execute()

        # Must fail: exit_code non-zero due to MemoryError or SIGKILL/SIGSEGV from OS
        assert result.exit_code != 0
        assert (
            "MemoryError" in result.stderr
            or result.exit_code in (-9, 137, 1, 139)
            or len(result.stdout) == 0
        )


@pytest.mark.asyncio
async def test_path_escape_attempt_blocked():
    """Acceptance Criteria: Attempting to execute with a CWD outside the designated workspace jail is blocked."""
    with tempfile.TemporaryDirectory() as temp_dir:
        outside_dir = "/etc" if sys.platform != "win32" else "C:\\Windows"

        # 1. Direct validation check raises PermissionError
        with pytest.raises(PermissionError) as exc_info:
            validate_workspace_jail(workspace_path=temp_dir, cwd=outside_dir)

        assert "escapes workspace jail" in str(exc_info.value)

        # 2. Worker creation with outside CWD is blocked before execution
        with pytest.raises(PermissionError):
            create_sandboxed_worker(
                cmd=["echo", "escaped"],
                workspace_path=temp_dir,
                cwd=outside_dir,
            )


@pytest.mark.asyncio
async def test_allowlist_env_scrubbing_prevents_secret_leakage():
    """Technical Decision & Acceptance Criteria: Allowlist-based scrubbing drops all un-allowlisted

    secrets and ambient tokens from child process environment.
    """
    # 1. Inject sensitive secrets into ambient parent environment
    os.environ["REDCELL_OPENAI_API_KEY"] = "sk-super-secret-key-12345"
    os.environ["SECRET_DATABASE_PASSWORD"] = "admin_super_secret_db_pass"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            # Verify scrub_environment helper drops all secrets
            clean_env = scrub_environment(workspace_path=temp_dir)

            assert "REDCELL_OPENAI_API_KEY" not in clean_env
            assert "SECRET_DATABASE_PASSWORD" not in clean_env
            assert "AWS_SECRET_ACCESS_KEY" not in clean_env

            # Allowed system keys must be preserved
            assert "PATH" in clean_env
            assert clean_env.get("TMPDIR") == os.path.join(temp_dir, "tmp")

            # 2. Execute process to assert secrets are inaccessible inside child process
            test_script = (
                "import os, sys\n"
                "leaked = [k for k in ['REDCELL_OPENAI_API_KEY', 'SECRET_DATABASE_PASSWORD', 'AWS_SECRET_ACCESS_KEY'] if k in os.environ]\n"
                "if leaked:\n"
                "    print(f'LEAKED: {leaked}')\n"
                "    sys.exit(1)\n"
                "else:\n"
                "    print('ENVIRONMENT_CLEAN_NO_LEAKS')\n"
            )

            worker = create_sandboxed_worker(
                cmd=["python3", "-c", test_script],
                workspace_path=temp_dir,
            )

            result = await worker.execute()
            assert result.exit_code == 0
            assert "ENVIRONMENT_CLEAN_NO_LEAKS" in result.stdout
            assert "LEAKED" not in result.stdout
    finally:
        os.environ.pop("REDCELL_OPENAI_API_KEY", None)
        os.environ.pop("SECRET_DATABASE_PASSWORD", None)
        os.environ.pop("AWS_SECRET_ACCESS_KEY", None)


@pytest.mark.asyncio
async def test_sandboxed_worker_standard_execution_in_jail():
    """Verify sandboxed worker successfully executes in-jail command within workspace directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        script = (
            "import os\n"
            "print(f'CWD: {os.path.realpath(os.getcwd())}')\n"
            "print('SANDBOX_OK')\n"
        )

        worker = create_sandboxed_worker(
            cmd=["python3", "-c", script],
            workspace_path=temp_dir,
            limits=ResourceLimits(max_memory_mb=512, max_cpu_sec=10, timeout_sec=15.0),
        )

        result = await worker.execute()
        assert result.exit_code == 0
        assert "SANDBOX_OK" in result.stdout
        assert os.path.realpath(temp_dir) in result.stdout
