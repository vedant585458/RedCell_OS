"""Integration tests for the WebSocket event endpoint and pub/sub broadcaster."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.ws import ConnectionManager
from app.main import create_app
from app.orchestrator import Orchestrator, OrchestratorEvent
from fastapi import WebSocket
from fastapi.testclient import TestClient


def test_websocket_connection_and_handshake():
    app = create_app()
    with TestClient(app) as client, client.websocket_connect("/ws/events") as websocket:
        data = websocket.receive_json()
        assert data["event_type"] == "connection_established"
        assert data["seq"] >= 0
        assert data["payload"]["status"] == "CONNECTED"


@pytest.mark.asyncio
async def test_connection_manager_broadcast():
    manager = ConnectionManager()

    mock_ws1 = MagicMock(spec=WebSocket)
    mock_ws1.send_json = AsyncMock()

    mock_ws2 = MagicMock(spec=WebSocket)
    mock_ws2.send_json = AsyncMock()

    manager._active_connections.add(mock_ws1)
    manager._active_connections.add(mock_ws2)
    assert manager.connection_count == 2

    test_event = OrchestratorEvent(
        seq=1,
        event_type="agent_state_changed",
        correlation_id="corr-test-ws",
        payload={"state": "EXECUTING", "tool": "nmap"},
    )

    sent_count = await manager.broadcast_event(test_event)
    assert sent_count == 2
    mock_ws1.send_json.assert_awaited_once()
    mock_ws2.send_json.assert_awaited_once()

    await manager.disconnect(mock_ws1)
    assert manager.connection_count == 1
    await manager.disconnect(mock_ws2)
    assert manager.connection_count == 0


@pytest.mark.asyncio
async def test_connection_manager_drops_dead_sockets():
    manager = ConnectionManager()

    mock_live = MagicMock(spec=WebSocket)
    mock_live.send_json = AsyncMock()

    mock_dead = MagicMock(spec=WebSocket)
    mock_dead.send_json = AsyncMock(side_effect=RuntimeError("Socket closed"))

    manager._active_connections.add(mock_live)
    manager._active_connections.add(mock_dead)

    test_event = {"seq": 2, "event_type": "heartbeat"}
    sent_count = await manager.broadcast_event(test_event)

    assert sent_count == 1
    assert manager.connection_count == 1
    assert mock_dead not in manager._active_connections


@pytest.mark.asyncio
async def test_orchestrator_event_subscription():
    orchestrator = Orchestrator()
    received_events = []

    async def subscriber(event):
        received_events.append(event)

    orchestrator.register_event_subscriber(subscriber)
    await orchestrator.start()

    await orchestrator.emit_event(
        event_type="task_completed",
        correlation_id="corr-123",
        payload={"result": "success"},
    )

    await orchestrator.emit_event(
        event_type="report_ready",
        correlation_id="corr-123",
        payload={"path": "report.md"},
    )

    await asyncio.sleep(0.05)
    await orchestrator.stop()

    assert len(received_events) == 2
    assert received_events[0].event_type == "task_completed"
    assert received_events[1].event_type == "report_ready"
