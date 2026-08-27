"""Near-real-time terminal output streaming with rate-limited coalescing windows to prevent event storms."""

import asyncio
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.orchestrator.core import global_orchestrator
from app.terminal.session import TerminalOutputLine, TerminalSession

logger = get_logger("terminal.streaming")

DEFAULT_COALESCE_WINDOW_SEC = 0.2  # ~200ms window (Technical Decision)
DEFAULT_MAX_CHUNK_CHARS = 4096  # Max buffer size before immediate flush


class CommandOutputEventPayload(BaseModel):
    """Structured payload for streamed stdout/stderr terminal chunks delivered to WebSocket clients."""

    session_id: str
    task_id: str
    agent_id: str
    engagement_id: str
    stream: str = Field(description="'stdout' | 'stderr' | 'system'")
    chunk_text: str
    line_count: int
    is_eof: bool = False
    correlation_id: str
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class TerminalOutputCoalescer:
    """Coalesces rapid terminal line emissions into ~200ms windows to bound WebSocket event rates and prevent event storms."""

    def __init__(
        self,
        session_id: str,
        task_id: str,
        agent_id: str,
        engagement_id: str,
        coalesce_window_sec: float = DEFAULT_COALESCE_WINDOW_SEC,
        max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
        correlation_id: str = "",
    ) -> None:
        self.session_id = session_id
        self.task_id = task_id
        self.agent_id = agent_id
        self.engagement_id = engagement_id
        self.coalesce_window_sec = coalesce_window_sec
        self.max_chunk_chars = max_chunk_chars
        self.correlation_id = correlation_id or f"corr-stream-{session_id}-{uuid.uuid4().hex[:6]}"

        self._buffer: list[str] = []
        self._buffer_chars: int = 0
        self._current_stream: str = "stdout"
        self._timer_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._emitted_chunks_count: int = 0
        self._is_closed: bool = False

    @property
    def emitted_chunks_count(self) -> int:
        return self._emitted_chunks_count

    async def push_line(self, text: str, stream: str = "stdout") -> None:
        """Push a line into the coalescing buffer, triggering a scheduled flush or immediate size-based flush."""
        if self._is_closed:
            return

        async with self._lock:
            # If stream changes (e.g. stdout -> stderr), flush current buffer first
            if self._buffer and stream != self._current_stream:
                await self._flush_internal(is_eof=False)

            self._current_stream = stream
            self._buffer.append(text)
            self._buffer_chars += len(text)

            # Check if buffer size reached immediate threshold
            if self._buffer_chars >= self.max_chunk_chars:
                if self._timer_task and not self._timer_task.done():
                    self._timer_task.cancel()
                await self._flush_internal(is_eof=False)
                return

            # Schedule time-window flush if not already running
            if self._timer_task is None or self._timer_task.done():
                self._timer_task = asyncio.create_task(self._schedule_window_flush())

    async def _schedule_window_flush(self) -> None:
        """Wait for the duration of the coalescing window then flush buffered output."""
        try:
            await asyncio.sleep(self.coalesce_window_sec)
            async with self._lock:
                await self._flush_internal(is_eof=False)
        except asyncio.CancelledError:
            pass

    async def _flush_internal(self, is_eof: bool = False) -> CommandOutputEventPayload | None:
        """Internal flush executing under lock."""
        if not self._buffer and not is_eof:
            return None

        chunk_text = "\n".join(self._buffer) if self._buffer else ""
        line_count = len(self._buffer)
        stream = self._current_stream

        self._buffer.clear()
        self._buffer_chars = 0
        self._timer_task = None
        self._emitted_chunks_count += 1

        payload = CommandOutputEventPayload(
            session_id=self.session_id,
            task_id=self.task_id,
            agent_id=self.agent_id,
            engagement_id=self.engagement_id,
            stream=stream,
            chunk_text=chunk_text,
            line_count=line_count,
            is_eof=is_eof,
            correlation_id=self.correlation_id,
        )

        # Broadcast command_output event over orchestrator bus
        await global_orchestrator.emit_event(
            event_type="command_output",
            correlation_id=self.correlation_id,
            engagement_id=self.engagement_id,
            agent_id=self.agent_id,
            task_id=self.task_id,
            payload=payload.model_dump(),
        )

        logger.debug(
            f"Emitted CommandOutput chunk #{self._emitted_chunks_count} ({line_count} lines, is_eof={is_eof})",
            session_id=self.session_id,
            stream=stream,
            lines=line_count,
        )

        return payload

    async def flush_and_close(self) -> None:
        """Cancel any pending window timer and immediately emit final EOF chunk."""
        async with self._lock:
            self._is_closed = True
            if self._timer_task and not self._timer_task.done():
                self._timer_task.cancel()
            await self._flush_internal(is_eof=True)


class TerminalStreamer:
    """Attaches to a TerminalSession and automatically streams coalesced output chunks during command executions."""

    def __init__(
        self,
        session: TerminalSession,
        coalesce_window_sec: float = DEFAULT_COALESCE_WINDOW_SEC,
    ) -> None:
        self.session = session
        self.coalesce_window_sec = coalesce_window_sec
        self._coalescer: TerminalOutputCoalescer | None = None
        self._is_active: bool = False

    def start(self, correlation_id: str = "") -> None:
        """Start listening to session output and initialize coalescing streamer."""
        if self._is_active:
            return

        self._coalescer = TerminalOutputCoalescer(
            session_id=self.session.session_id,
            task_id=self.session.task_id,
            agent_id=self.session.agent_id,
            engagement_id=self.session.engagement_id,
            coalesce_window_sec=self.coalesce_window_sec,
            correlation_id=correlation_id,
        )
        self.session.ring_buffer.subscribe(self._on_line)
        self._is_active = True

    async def stop(self) -> None:
        """Stop listening and flush all pending output to EOF."""
        if not self._is_active:
            return

        self.session.ring_buffer.unsubscribe(self._on_line)
        self._is_active = False
        if self._coalescer:
            await self._coalescer.flush_and_close()

    def _on_line(self, line: TerminalOutputLine) -> None:
        """Callback invoked when a new line is added to session ring buffer."""
        if self._coalescer:
            asyncio.create_task(self._coalescer.push_line(line.text, line.stream))
