"""Unit and integration tests for TerminalSession, circular ring buffering, command history tracking, and session manager."""

import tempfile

import pytest
from app.terminal.session import (
    TerminalRingBuffer,
    TerminalSession,
    TerminalSessionManager,
)


@pytest.mark.asyncio
async def test_terminal_session_command_execution_and_streaming():
    """Acceptance Criteria: Executing a command via session records history and streams output into ring buffer."""
    with tempfile.TemporaryDirectory() as temp_dir:
        session = TerminalSession(
            session_id="term-agent-recon-01-task-01",
            agent_id="agent-recon-01",
            task_id="task-recon-01",
            engagement_id="eng-term-test",
            workspace_path=temp_dir,
        )

        streamed_lines: list[str] = []

        # Subscribe to live streaming output
        session.ring_buffer.subscribe(lambda line: streamed_lines.append(line.text))

        # Execute multi-line command
        result = await session.execute_command(
            cmd=[
                "python3",
                "-c",
                "print('First Line'); print('Second Line'); print('Third Line')",
            ],
            timeout_sec=10.0,
        )

        assert result.exit_code == 0
        assert "First Line" in result.stdout
        assert "Second Line" in result.stdout
        assert "Third Line" in result.stdout

        # Verify ring buffer has captured lines
        buffer_lines = session.get_recent_output()
        buffer_texts = [line_item.text for line_item in buffer_lines]

        assert any("First Line" in t for t in buffer_texts)
        assert any("Second Line" in t for t in buffer_texts)
        assert any("Third Line" in t for t in buffer_texts)

        # Verify real-time subscriber received lines
        assert any("First Line" in t for t in streamed_lines)
        assert any("Second Line" in t for t in streamed_lines)
        assert any("Third Line" in t for t in streamed_lines)


@pytest.mark.asyncio
async def test_terminal_command_history_tracking():
    """Acceptance Criteria: Chronological command history list is maintained per session."""
    with tempfile.TemporaryDirectory() as temp_dir:
        session = TerminalSession(
            session_id="term-agent-vuln-01",
            agent_id="agent-vuln-01",
            task_id="task-vuln-01",
            engagement_id="eng-term-test",
            workspace_path=temp_dir,
        )

        # Execute 3 commands in sequence
        await session.execute_command(cmd=["echo", "Hello Command 1"])
        await session.execute_command(
            cmd=["python3", "-c", "import sys; sys.stderr.write('Warning 2\\n')"]
        )
        await session.execute_command(cmd=["python3", "-c", "import sys; sys.exit(42)"])

        history = session.get_history()
        assert len(history) == 3

        # Command 1 assertions
        assert history[0].command == ["echo", "Hello Command 1"]
        assert history[0].exit_code == 0
        assert "Hello Command 1" in history[0].stdout_summary
        assert history[0].duration_sec >= 0.0

        # Command 2 assertions (stderr output)
        assert history[1].exit_code == 0
        assert "Warning 2" in history[1].stderr_summary

        # Command 3 assertions (non-zero exit code)
        assert history[2].exit_code == 42
        assert history[2].timed_out is False


def test_terminal_ring_buffer_circular_eviction():
    """Unit Test: Ring buffer strictly enforces maximum line limit, evicting oldest lines when full."""
    buffer = TerminalRingBuffer(max_lines=5)

    for i in range(1, 9):
        buffer.add_line(f"Log Line {i}")

    assert buffer.total_lines_emitted == 8

    # Buffer should hold only the latest 5 lines (Lines 4, 5, 6, 7, 8)
    lines = buffer.get_lines()
    assert len(lines) == 5
    assert lines[0].text == "Log Line 4"
    assert lines[-1].text == "Log Line 8"
    assert lines[-1].line_number == 8


@pytest.mark.asyncio
async def test_interactive_command_limitation_documented_notice():
    """Risk Mitigation Test: Interactive tool executions emit documented limitation notice in non-PTY session."""
    with tempfile.TemporaryDirectory() as temp_dir:
        session = TerminalSession(
            session_id="term-agent-01",
            agent_id="agent-01",
            task_id="task-01",
            engagement_id="eng-1",
            workspace_path=temp_dir,
        )

        await session.execute_command(
            cmd=["echo", "simulated interactive"],
            is_interactive=True,
        )

        history = session.get_history()
        assert len(history) == 1
        assert history[0].is_interactive is True

        buffer_text = session.ring_buffer.get_full_text()
        assert (
            "Command flagged as interactive; running in non-PTY batch mode"
            in buffer_text
        )


@pytest.mark.asyncio
async def test_terminal_session_manager_lifecycle():
    """Verify TerminalSessionManager handles session creation, lookup, and closing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        manager = TerminalSessionManager()

        session = await manager.create_session(
            agent_id="agent-exploit-01",
            task_id="task-exploit-01",
            engagement_id="eng-1",
            workspace_path=temp_dir,
        )

        session_id = session.session_id
        assert session_id == "term-agent-exploit-01-task-exploit-01"

        # Lookups
        by_id = await manager.get_session(session_id)
        assert by_id is not None
        assert by_id.session_id == session_id

        by_task = await manager.get_session_by_task("task-exploit-01")
        assert by_task is not None
        assert by_task.session_id == session_id

        active = await manager.list_active_sessions()
        assert len(active) == 1

        # Close session
        closed = await manager.close_session(session_id)
        assert closed is True
        assert await manager.get_session(session_id) is None
        assert len(await manager.list_active_sessions()) == 0
