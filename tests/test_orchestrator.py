"""Unit tests for the Orchestrator core loop, task tracking, and queue lifecycle."""

import asyncio

import pytest
from app.orchestrator import (
    Orchestrator,
    OrchestratorCommand,
    OrchestratorEvent,
    OrchestratorState,
)


@pytest.mark.asyncio
async def test_orchestrator_start_stop_clean_lifecycle():
    orchestrator = Orchestrator()
    assert orchestrator.state == OrchestratorState.STOPPED

    await orchestrator.start()
    assert orchestrator.state == OrchestratorState.RUNNING
    assert orchestrator.is_running is True

    # Check that worker tasks are active
    assert orchestrator._command_worker_task is not None
    assert orchestrator._event_worker_task is not None
    assert not orchestrator._command_worker_task.done()

    # Graceful stop
    await orchestrator.stop()
    assert orchestrator.state == OrchestratorState.STOPPED
    assert orchestrator.is_running is False
    assert len(orchestrator._tracked_tasks) == 0


@pytest.mark.asyncio
async def test_orchestrator_command_processing():
    orchestrator = Orchestrator()
    await orchestrator.start()

    handled_commands: list[OrchestratorCommand] = []

    async def sample_handler(cmd: OrchestratorCommand) -> None:
        handled_commands.append(cmd)

    orchestrator.register_command_handler("SAMPLE_ACTION", sample_handler)

    test_cmd = OrchestratorCommand(
        command_type="SAMPLE_ACTION",
        payload={"target": "127.0.0.1"},
    )

    await orchestrator.submit_command(test_cmd)
    # Allow command loop to process
    await asyncio.sleep(0.05)

    assert len(handled_commands) == 1
    assert handled_commands[0].command_type == "SAMPLE_ACTION"
    assert handled_commands[0].payload["target"] == "127.0.0.1"

    await orchestrator.stop()


@pytest.mark.asyncio
async def test_orchestrator_event_emission_and_subscribers():
    orchestrator = Orchestrator()
    await orchestrator.start()

    received_events: list[OrchestratorEvent] = []

    async def event_subscriber(event: OrchestratorEvent) -> None:
        received_events.append(event)

    orchestrator.register_event_subscriber(event_subscriber)

    await orchestrator.emit_event(
        event_type="agent_state_changed",
        correlation_id="corr-test-123",
        payload={"state": "PLANNING"},
    )
    await orchestrator.emit_event(
        event_type="task_started",
        correlation_id="corr-test-123",
        payload={"task_id": "T01"},
    )

    await asyncio.sleep(0.05)

    assert len(received_events) == 2
    assert received_events[0].seq == 1
    assert received_events[0].event_type == "agent_state_changed"
    assert received_events[1].seq == 2
    assert received_events[1].event_type == "task_started"

    await orchestrator.stop()


@pytest.mark.asyncio
async def test_orchestrator_task_tracking_and_exception_handling():
    orchestrator = Orchestrator()
    await orchestrator.start()

    # Track a normal task
    async def normal_job():
        await asyncio.sleep(0.01)
        return "done"

    # Track a failing task (exception should be caught and discarded cleanly without crashing loop)
    async def failing_job():
        await asyncio.sleep(0.01)
        raise ValueError("Simulated job failure")

    task1 = orchestrator.track_task(normal_job(), name="normal_task")
    task2 = orchestrator.track_task(failing_job(), name="failing_task")

    await asyncio.sleep(0.05)

    assert task1.done()
    assert task2.done()
    assert len(orchestrator._tracked_tasks) == 0
    assert orchestrator.is_running is True

    await orchestrator.stop()
