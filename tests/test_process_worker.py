"""Unit tests for the WorkerProcess subprocess execution wrapper."""

import os
import sys

import pytest
from app.process.worker import WorkerProcess


@pytest.mark.asyncio
async def test_worker_process_success():
    worker = WorkerProcess(cmd=["echo", "hello redcell"])
    result = await worker.execute()

    assert result.exit_code == 0
    assert "hello redcell" in result.stdout
    assert result.stderr == ""
    assert result.timed_out is False
    assert result.duration_sec >= 0
    assert result.pid is not None


@pytest.mark.asyncio
async def test_worker_process_nonzero_exit():
    worker = WorkerProcess(
        cmd=[
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('fatal error occurred\\n'); sys.exit(42)",
        ]
    )
    result = await worker.execute()

    assert result.exit_code == 42
    assert "fatal error occurred" in result.stderr
    assert result.timed_out is False


@pytest.mark.asyncio
async def test_worker_process_timeout():
    # Attempt to sleep for 5 seconds with a 0.2s timeout
    worker = WorkerProcess(
        cmd=[sys.executable, "-c", "import time; time.sleep(5)"],
        timeout_sec=0.2,
    )
    result = await worker.execute()

    assert result.timed_out is True
    assert result.duration_sec < 1.0  # Must terminate quickly (< 1s)


@pytest.mark.asyncio
async def test_worker_process_line_streaming():
    captured_lines: list[str] = []

    async def handle_line(line: str) -> None:
        captured_lines.append(line.strip())

    script = "print('line 1'); print('line 2'); print('line 3')"
    worker = WorkerProcess(
        cmd=[sys.executable, "-c", script],
        on_stdout_line=handle_line,
    )
    result = await worker.execute()

    assert result.exit_code == 0
    assert captured_lines == ["line 1", "line 2", "line 3"]


@pytest.mark.asyncio
async def test_worker_process_large_output_no_deadlock():
    # Emit 5,000 lines to ensure pipes drain smoothly without buffer deadlock
    script = "for i in range(5000): print(f'data_row_{i}')"
    worker = WorkerProcess(
        cmd=[sys.executable, "-c", script],
        timeout_sec=5.0,
    )
    result = await worker.execute()

    assert result.exit_code == 0
    assert "data_row_0" in result.stdout
    assert "data_row_4999" in result.stdout
    assert result.stdout.count("\n") == 5000


@pytest.mark.asyncio
async def test_worker_process_cwd_and_env(tmp_path):
    custom_cwd = str(tmp_path)
    custom_env = {**os.environ, "CUSTOM_TEST_VAR": "REDCELL_PROBE_123"}

    script = "import os; print(os.getcwd()); print(os.environ.get('CUSTOM_TEST_VAR'))"
    worker = WorkerProcess(
        cmd=[sys.executable, "-c", script],
        cwd=custom_cwd,
        env=custom_env,
    )
    result = await worker.execute()

    assert result.exit_code == 0
    assert custom_cwd in result.stdout
    assert "REDCELL_PROBE_123" in result.stdout
