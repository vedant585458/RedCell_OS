"""Terminal package managing logical terminal sessions, ring-buffered streaming, and command history."""

from .session import (
    DEFAULT_RING_BUFFER_LINES,
    TerminalCommandRecord,
    TerminalOutputLine,
    TerminalRingBuffer,
    TerminalSession,
    TerminalSessionManager,
    global_terminal_manager,
)

__all__ = [
    "TerminalOutputLine",
    "TerminalCommandRecord",
    "TerminalRingBuffer",
    "TerminalSession",
    "TerminalSessionManager",
    "DEFAULT_RING_BUFFER_LINES",
    "global_terminal_manager",
]
