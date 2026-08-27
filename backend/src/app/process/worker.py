"""Asynchronous subprocess worker primitive with line-buffered streaming, timeouts, and process-group isolation."""

import asyncio
import os
import signal
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger

logger = get_logger("process.worker")

LineCallback = Callable[[str], Awaitable[None]]


class ProcessResult(BaseModel):
    """Structured result returned by a WorkerProcess execution."""

    exit_code: int = Field(description="Process exit code (0 for success, non-zero for failure)")
    stdout: str = Field(default="", description="Complete captured stdout output")
    stderr: str = Field(default="", description="Complete captured stderr output")
    duration_sec: float = Field(description="Execution duration in seconds")
    timed_out: bool = Field(
        default=False, description="Whether execution was terminated due to timeout"
    )
    pid: int | None = Field(default=None, description="Operating system process ID")
    pgid: int | None = Field(default=None, description="Operating system process group ID")
    command: list[str] = Field(description="Command line arguments executed")


class WorkerProcess:
    """Async worker managing isolated subprocess execution with line-buffered streaming and fail-safe termination."""

    def __init__(
        self,
        cmd: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: float | None = None,
        on_stdout_line: LineCallback | None = None,
        on_stderr_line: LineCallback | None = None,
        preexec_fn: Callable[[], Any] | None = None,
    ) -> None:
        self.cmd = cmd
        self.cwd = cwd
        self.env = env
        self.timeout_sec = timeout_sec
        self.on_stdout_line = on_stdout_line
        self.on_stderr_line = on_stderr_line
        self.preexec_fn = preexec_fn

        self.process: asyncio.subprocess.Process | None = None
        self.pid: int | None = None
        self.pgid: int | None = None
        self._stdout_chunks: list[str] = []
        self._stderr_chunks: list[str] = []
        self._is_killed: bool = False

    async def execute(self) -> ProcessResult:
        """Spawn the child subprocess, stream stdout/stderr, enforce timeout, and return structured result."""
        start_time = time.monotonic()
        timed_out = False

        # Ensure cwd exists if provided
        if self.cwd:
            os.makedirs(self.cwd, exist_ok=True)

        is_posix = sys.platform != "win32"

        try:
            # Spawn in a new session / process group on POSIX to guarantee fail-safe kill
            self.process = await asyncio.create_subprocess_exec(
                *self.cmd,
                cwd=self.cwd,
                env=self.env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=is_posix,
                preexec_fn=self.preexec_fn if is_posix else None,
            )

            self.pid = self.process.pid
            if is_posix and self.pid:
                try:
                    self.pgid = os.getpgid(self.pid)
                except ProcessLookupError:
                    self.pgid = self.pid

            logger.debug(
                "Spawned worker subprocess",
                cmd=self.cmd,
                pid=self.pid,
                pgid=self.pgid,
                cwd=self.cwd,
            )

            # Concurrent reader tasks for stdout and stderr
            stdout_task = asyncio.create_task(
                self._read_stream(self.process.stdout, self._stdout_chunks, self.on_stdout_line)
            )
            stderr_task = asyncio.create_task(
                self._read_stream(self.process.stderr, self._stderr_chunks, self.on_stderr_line)
            )

            if self.timeout_sec is not None and self.timeout_sec > 0:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(self.process.wait(), stdout_task, stderr_task),
                        timeout=self.timeout_sec,
                    )
                except TimeoutError:
                    timed_out = True
                    logger.warning(
                        "Worker subprocess timed out. Terminating process group...",
                        pid=self.pid,
                        pgid=self.pgid,
                        timeout_sec=self.timeout_sec,
                    )
                    await self.kill()
                    # Wait for stream tasks to finish draining
                    await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            else:
                await asyncio.gather(self.process.wait(), stdout_task, stderr_task)

            exit_code = self.process.returncode if self.process.returncode is not None else -1
            if timed_out and exit_code == 0:
                exit_code = 124  # Standard POSIX timeout exit code

        except Exception as err:
            logger.error(
                "Error during worker process execution",
                cmd=self.cmd,
                pid=self.pid,
                error=str(err),
            )
            await self.kill()
            exit_code = -1
            self._stderr_chunks.append(f"\nWorkerProcess Execution Error: {err}\n")

        duration = time.monotonic() - start_time

        return ProcessResult(
            exit_code=exit_code,
            stdout="".join(self._stdout_chunks),
            stderr="".join(self._stderr_chunks),
            duration_sec=round(duration, 4),
            timed_out=timed_out,
            pid=self.pid,
            pgid=self.pgid,
            command=self.cmd,
        )

    async def _read_stream(
        self,
        stream: asyncio.StreamReader | None,
        chunks: list[str],
        callback: LineCallback | None,
    ) -> None:
        """Asynchronously read lines from stream, buffer chunks, and invoke line callback."""
        if not stream:
            return

        while not stream.at_eof():
            try:
                line_bytes = await stream.readline()
                if not line_bytes:
                    break

                line_str = line_bytes.decode(errors="replace")
                chunks.append(line_str)

                if callback:
                    try:
                        await callback(line_str)
                    except Exception as cb_err:
                        logger.warning(f"Error in stream callback: {cb_err}")

            except Exception:
                break

    async def kill(self) -> None:
        """Forcefully terminate the process and its entire process group to avoid zombie processes."""
        if self._is_killed:
            return
        self._is_killed = True

        if not self.process:
            return

        # Attempt to kill the entire process group
        if sys.platform != "win32" and self.pgid:
            try:
                os.killpg(self.pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception as e:
                logger.debug(f"Process group kill notice: {e}")
        else:
            try:
                self.process.kill()
            except ProcessLookupError:
                pass

        try:
            await asyncio.wait_for(self.process.wait(), timeout=1.0)
        except (TimeoutError, asyncio.CancelledError):
            pass

    async def terminate(self) -> None:
        """Send SIGTERM to process group, waiting briefly before escalating to SIGKILL."""
        if self._is_killed or not self.process:
            return

        if sys.platform != "win32" and self.pgid:
            try:
                os.killpg(self.pgid, signal.SIGTERM)
            except ProcessLookupError:
                return
        else:
            try:
                self.process.terminate()
            except ProcessLookupError:
                return

        try:
            await asyncio.wait_for(self.process.wait(), timeout=0.5)
        except (TimeoutError, asyncio.CancelledError):
            await self.kill()
