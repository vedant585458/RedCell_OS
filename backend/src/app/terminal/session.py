"""Logical Terminal Session abstraction wrapping WorkerProcess with circular ring-buffered output and command history."""

import asyncio
import collections
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.orchestrator.core import global_orchestrator
from app.process.registry import global_process_registry
from app.process.worker import ProcessResult, WorkerProcess

logger = get_logger("terminal.session")

DEFAULT_RING_BUFFER_LINES = 1000
MAX_OUTPUT_SUMMARY_CHARS = 1000


class TerminalOutputLine(BaseModel):
    """Structured line emitted to the terminal output stream."""

    line_number: int
    stream: str = Field(description="'stdout' | 'stderr' | 'system'")
    text: str
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class TerminalCommandRecord(BaseModel):
    """Historical record of an executed command within the terminal session."""

    command_id: str = Field(default_factory=lambda: f"cmd-{uuid.uuid4().hex[:8]}")
    command: list[str]
    exit_code: int
    started_at: str
    completed_at: str
    duration_sec: float
    timed_out: bool
    pid: int | None = None
    stdout_summary: str = Field(default="")
    stderr_summary: str = Field(default="")
    is_interactive: bool = Field(
        default=False,
        description="Flag indicating if command was interactive (Documented non-PTY limitation)",
    )


class TerminalRingBuffer:
    """Thread-safe circular ring buffer for live terminal streaming and historical line retrieval."""

    def __init__(self, max_lines: int = DEFAULT_RING_BUFFER_LINES) -> None:
        self.max_lines = max_lines
        self._buffer: collections.deque[TerminalOutputLine] = collections.deque(maxlen=max_lines)
        self._line_counter = 0
        self._subscribers: list[Callable[[TerminalOutputLine], Awaitable[None] | None]] = []
        self._lock = asyncio.Lock()

    @property
    def total_lines_emitted(self) -> int:
        return self._line_counter

    def add_line(self, text: str, stream: str = "stdout") -> TerminalOutputLine:
        """Add a line to the ring buffer and dispatch to all active stream subscribers."""
        self._line_counter += 1
        line = TerminalOutputLine(
            line_number=self._line_counter,
            stream=stream,
            text=text.rstrip("\r\n"),
        )
        self._buffer.append(line)

        # Notify subscribers
        for sub in list(self._subscribers):
            try:
                res = sub(line)
                if hasattr(res, "__await__"):
                    asyncio.create_task(res)  # type: ignore[arg-type]
            except Exception as e:
                logger.warning(f"Error in terminal subscriber callback: {e}")

        return line

    def get_lines(self, count: int | None = None) -> list[TerminalOutputLine]:
        """Retrieve the most recent N lines from the ring buffer."""
        lines = list(self._buffer)
        if count is not None and count > 0:
            return lines[-count:]
        return lines

    def get_full_text(self) -> str:
        """Concatenate all lines currently held in the ring buffer."""
        return "\n".join(line.text for line in self._buffer)

    def subscribe(self, callback: Callable[[TerminalOutputLine], Awaitable[None] | None]) -> None:
        """Subscribe an async or sync callback to real-time line emissions."""
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[TerminalOutputLine], Awaitable[None] | None]) -> None:
        """Unsubscribe a callback."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def clear(self) -> None:
        """Flush the ring buffer."""
        self._buffer.clear()


class TerminalSession:
    """Logical terminal session bound to an agent-task workspace, providing live streaming and command history.

    Technical Decision: Terminal session is logical (non-PTY) for MVP, sufficient for scripted security tool execution.
    Documented Limitation: Interactive tools expecting raw stdin (e.g. interactive gdb or password prompts) are not supported.
    """

    def __init__(
        self,
        session_id: str,
        agent_id: str,
        task_id: str,
        engagement_id: str,
        workspace_path: str,
        env: dict[str, str] | None = None,
        max_buffer_lines: int = DEFAULT_RING_BUFFER_LINES,
    ) -> None:
        self.session_id = session_id
        self.agent_id = agent_id
        self.task_id = task_id
        self.engagement_id = engagement_id
        self.workspace_path = workspace_path
        self.cwd = workspace_path
        self.env = env or os.environ.copy()

        self.ring_buffer = TerminalRingBuffer(max_lines=max_buffer_lines)
        self.history: list[TerminalCommandRecord] = []
        self.active_process: WorkerProcess | None = None
        self._lock = asyncio.Lock()

    @property
    def is_running_command(self) -> bool:
        return self.active_process is not None

    async def execute_command(
        self,
        cmd: list[str],
        timeout_sec: float | None = 60.0,
        env_overrides: dict[str, str] | None = None,
        is_interactive: bool = False,
        correlation_id: str = "",
    ) -> ProcessResult:
        """Execute a tool command within the workspace session, streaming output to the ring buffer and logging history."""
        if is_interactive:
            logger.warning(
                "Interactive command executed in non-PTY logical terminal session. Stdin is closed by design.",
                cmd=cmd,
                session_id=self.session_id,
            )
            self.ring_buffer.add_line(
                "[SYSTEM NOTICE] Command flagged as interactive; running in non-PTY batch mode with stdin closed.",
                stream="system",
            )

        # Log system start banner in terminal ring buffer
        cmd_str = " ".join(cmd)
        self.ring_buffer.add_line(f"$ {cmd_str}", stream="system")

        start_time_mono = time.monotonic()
        start_time_iso = datetime.now(UTC).isoformat()
        corr_id = correlation_id or f"corr-term-{self.session_id}-{uuid.uuid4().hex[:6]}"

        merged_env = self.env.copy()
        if env_overrides:
            merged_env.update(env_overrides)

        # Define streaming callbacks
        async def on_stdout(line: str) -> None:
            self.ring_buffer.add_line(line, stream="stdout")

        async def on_stderr(line: str) -> None:
            self.ring_buffer.add_line(line, stream="stderr")

        # 1. Instantiate WorkerProcess
        worker = WorkerProcess(
            cmd=cmd,
            cwd=self.cwd,
            env=merged_env,
            timeout_sec=timeout_sec,
            on_stdout_line=on_stdout,
            on_stderr_line=on_stderr,
        )

        async with self._lock:
            self.active_process = worker

        # 2. Register process in global registry for emergency kill-switch capability
        registered_record = None
        try:
            # Spawn and execute
            exec_task = asyncio.create_task(worker.execute())

            # Yield control to let worker spawn process PID
            await asyncio.sleep(0.01)
            if worker.pid:
                try:
                    registered_record = await global_process_registry.register(
                        worker=worker,
                        agent_id=self.agent_id,
                        command=cmd,
                        workspace_path=self.workspace_path,
                        engagement_id=self.engagement_id,
                        task_id=self.task_id,
                    )
                except Exception as reg_err:
                    logger.warning(f"Could not register worker in process registry: {reg_err}")

            result = await exec_task
        finally:
            async with self._lock:
                self.active_process = None

            if registered_record:
                await global_process_registry.unregister(
                    registered_record.process_id,
                    status="COMPLETED" if not result.timed_out else "TIMED_OUT",
                )

        completed_time_iso = datetime.now(UTC).isoformat()
        duration_sec = time.monotonic() - start_time_mono

        # Log completion in ring buffer
        status_msg = f"[Process exited with code {result.exit_code} in {duration_sec:.2f}s]"
        if result.timed_out:
            status_msg = f"[Process TIMED OUT after {timeout_sec}s and was terminated]"
        self.ring_buffer.add_line(status_msg, stream="system")

        # 3. Record command in session history
        history_rec = TerminalCommandRecord(
            command=cmd,
            exit_code=result.exit_code,
            started_at=start_time_iso,
            completed_at=completed_time_iso,
            duration_sec=round(duration_sec, 4),
            timed_out=result.timed_out,
            pid=result.pid,
            stdout_summary=result.stdout[:MAX_OUTPUT_SUMMARY_CHARS],
            stderr_summary=result.stderr[:MAX_OUTPUT_SUMMARY_CHARS],
            is_interactive=is_interactive,
        )
        self.history.append(history_rec)

        # 4. Emit command execution event over orchestrator bus
        await global_orchestrator.emit_event(
            event_type="terminal_command_executed",
            correlation_id=corr_id,
            engagement_id=self.engagement_id,
            agent_id=self.agent_id,
            task_id=self.task_id,
            payload={
                "session_id": self.session_id,
                "command": cmd,
                "exit_code": result.exit_code,
                "duration_sec": round(duration_sec, 4),
                "timed_out": result.timed_out,
                "pid": result.pid,
            },
        )

        return result

    async def kill(self) -> bool:
        """Kill the currently active process in this terminal session."""
        async with self._lock:
            if self.active_process:
                await self.active_process.kill()
                self.ring_buffer.add_line("[TERMINAL PROCESS KILLED BY OPERATOR]", stream="system")
                return True
        return False

    def get_history(self) -> list[TerminalCommandRecord]:
        """Return full chronological command history for this terminal session."""
        return list(self.history)

    def get_recent_output(self, lines: int = 100) -> list[TerminalOutputLine]:
        """Return the most recent N lines from the live ring buffer."""
        return self.ring_buffer.get_lines(count=lines)


class TerminalSessionManager:
    """Registry and lifecycle manager for all active agent TerminalSession instances."""

    def __init__(self) -> None:
        self._sessions: dict[str, TerminalSession] = {}
        self._task_index: dict[str, str] = {}  # task_id -> session_id
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        agent_id: str,
        task_id: str,
        engagement_id: str,
        workspace_path: str,
        env: dict[str, str] | None = None,
    ) -> TerminalSession:
        """Create or retrieve a TerminalSession bound to an agent and task workspace."""
        async with self._lock:
            session_id = f"term-{agent_id}-{task_id}"
            if session_id in self._sessions:
                return self._sessions[session_id]

            session = TerminalSession(
                session_id=session_id,
                agent_id=agent_id,
                task_id=task_id,
                engagement_id=engagement_id,
                workspace_path=workspace_path,
                env=env,
            )

            self._sessions[session_id] = session
            self._task_index[task_id] = session_id

            logger.info(
                f"Created logical TerminalSession '{session_id}' in workspace '{workspace_path}'",
                session_id=session_id,
                agent_id=agent_id,
                task_id=task_id,
            )
            return session

    async def get_session(self, session_id: str) -> TerminalSession | None:
        """Lookup session by session_id."""
        async with self._lock:
            return self._sessions.get(session_id)

    async def get_session_by_task(self, task_id: str) -> TerminalSession | None:
        """Lookup session by task_id."""
        async with self._lock:
            session_id = self._task_index.get(task_id)
            if session_id:
                return self._sessions.get(session_id)
            return None

    async def close_session(self, session_id: str) -> bool:
        """Close terminal session and kill any in-flight process."""
        async with self._lock:
            session = self._sessions.pop(session_id, None)
            if not session:
                return False

            if session.task_id in self._task_index:
                del self._task_index[session.task_id]

            await session.kill()
            logger.info(f"Closed TerminalSession '{session_id}'", session_id=session_id)
            return True

    async def list_active_sessions(self) -> list[TerminalSession]:
        """List all active terminal sessions."""
        async with self._lock:
            return list(self._sessions.values())


# Global singleton instance of TerminalSessionManager
global_terminal_manager = TerminalSessionManager()
