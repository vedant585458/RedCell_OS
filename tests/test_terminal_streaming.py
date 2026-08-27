"""Unit and integration tests for Terminal output streaming, coalescing rate-limit windows, and incremental CommandOutput event emission."""

import asyncio
import tempfile

import pytest
from app.orchestrator import global_orchestrator
from app.terminal.session import TerminalSession
from app.terminal.streaming import (
    CommandOutputEventPayload,
    TerminalOutputCoalescer,
    TerminalStreamer,
)


@pytest.mark.asyncio
async def test_incremental_streaming_events_for_long_running_command():
    """Acceptance Criteria & Technical Decision: Long-running command produces multiple incremental

    CommandOutput events over ~200ms coalescing windows, rather than a single giant payload at the end.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        session = TerminalSession(
            session_id="term-stream-test",
            agent_id="agent-recon-01",
            task_id="task-recon-01",
            engagement_id="eng-stream-test",
            workspace_path=temp_dir,
        )

        captured_output_events: list[CommandOutputEventPayload] = []

        async def capture_event(event):
            if event.event_type == "command_output":
                captured_output_events.append(
                    CommandOutputEventPayload(**event.payload)
                )

        global_orchestrator.register_event_subscriber(capture_event)
        await global_orchestrator.start()

        # Coalesce window = 0.1s (100ms for fast test execution)
        streamer = TerminalStreamer(session, coalesce_window_sec=0.1)
        streamer.start(correlation_id="corr-inc-stream")

        # Python script that emits output incrementally with 0.15s pauses between lines
        streaming_script = (
            "import time, sys\n"
            "for i in range(1, 4):\n"
            "    print(f'Incremental Output Line {i}', flush=True)\n"
            "    time.sleep(0.15)\n"
        )

        try:
            result = await session.execute_command(
                cmd=["python3", "-c", streaming_script],
                timeout_sec=10.0,
            )
            assert result.exit_code == 0

            # Stop streamer to flush final EOF
            await streamer.stop()
            await asyncio.sleep(0.05)

            # Assert: Multiple incremental events were received over time
            assert len(captured_output_events) >= 3

            # Check chunk contents
            all_chunks_text = "\n".join(e.chunk_text for e in captured_output_events)
            assert "Incremental Output Line 1" in all_chunks_text
            assert "Incremental Output Line 2" in all_chunks_text
            assert "Incremental Output Line 3" in all_chunks_text

            # Check that final chunk has EOF flag
            assert any(e.is_eof for e in captured_output_events)
        finally:
            await streamer.stop()
            global_orchestrator.unregister_event_subscriber(capture_event)
            await global_orchestrator.stop()


@pytest.mark.asyncio
async def test_coalescing_window_batches_rapid_bursts():
    """Risk Mitigation: Rapid bursts of output lines within the ~200ms window are coalesced into a single event."""
    captured_events = []

    async def capture_event(event):
        if event.event_type == "command_output":
            captured_events.append(event)

    global_orchestrator.register_event_subscriber(capture_event)
    await global_orchestrator.start()

    try:
        coalescer = TerminalOutputCoalescer(
            session_id="term-burst-test",
            task_id="task-01",
            agent_id="agent-01",
            engagement_id="eng-1",
            coalesce_window_sec=0.15,
        )

        # Push 10 rapid lines within 10ms (much faster than 150ms window)
        for i in range(1, 11):
            await coalescer.push_line(f"Rapid burst line {i}")
            await asyncio.sleep(0.001)

        # Before window timer fires, no event should be emitted yet
        assert len(captured_events) == 0

        # Wait for the coalescing window to fire (0.15s + buffer)
        await asyncio.sleep(0.25)

        # Exactly 1 coalesced event chunk should have been emitted containing all 10 lines
        assert len(captured_events) == 1
        payload = captured_events[0].payload
        assert payload["line_count"] == 10
        assert "Rapid burst line 1" in payload["chunk_text"]
        assert "Rapid burst line 10" in payload["chunk_text"]

        await coalescer.flush_and_close()
    finally:
        global_orchestrator.unregister_event_subscriber(capture_event)
        await global_orchestrator.stop()


@pytest.mark.asyncio
async def test_max_chunk_size_triggers_immediate_flush():
    """Verify that buffer size exceeding max_chunk_chars triggers an immediate flush without waiting for timer."""
    captured_events = []

    async def capture_event(event):
        if event.event_type == "command_output":
            captured_events.append(event)

    global_orchestrator.register_event_subscriber(capture_event)
    await global_orchestrator.start()

    try:
        # max_chunk_chars = 100, window = 1.0s
        coalescer = TerminalOutputCoalescer(
            session_id="term-size-test",
            task_id="task-01",
            agent_id="agent-01",
            engagement_id="eng-1",
            coalesce_window_sec=1.0,  # Long 1-second window
            max_chunk_chars=100,
        )

        # Push 150 characters (exceeds max_chunk_chars 100)
        large_line = "A" * 150
        await coalescer.push_line(large_line)

        # Must flush immediately without waiting for the 1.0s timer
        await asyncio.sleep(0.02)
        assert len(captured_events) == 1
        assert len(captured_events[0].payload["chunk_text"]) == 150

        await coalescer.flush_and_close()
    finally:
        global_orchestrator.unregister_event_subscriber(capture_event)
        await global_orchestrator.stop()
