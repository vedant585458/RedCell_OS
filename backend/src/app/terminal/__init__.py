"""Terminal package managing logical terminal sessions, ring-buffered streaming, coalesced output events, and command history."""

from .session import (
    DEFAULT_RING_BUFFER_LINES,
    TerminalCommandRecord,
    TerminalOutputLine,
    TerminalRingBuffer,
    TerminalSession,
    TerminalSessionManager,
    global_terminal_manager,
)
from .streaming import (
    DEFAULT_COALESCE_WINDOW_SEC,
    CommandOutputEventPayload,
    TerminalOutputCoalescer,
    TerminalStreamer,
)

__all__ = [
    "TerminalOutputLine",
    "TerminalCommandRecord",
    "TerminalRingBuffer",
    "TerminalSession",
    "TerminalSessionManager",
    "DEFAULT_RING_BUFFER_LINES",
    "global_terminal_manager",
    "CommandOutputEventPayload",
    "TerminalOutputCoalescer",
    "TerminalStreamer",
    "DEFAULT_COALESCE_WINDOW_SEC",
]
