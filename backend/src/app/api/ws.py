"""WebSocket event broadcast endpoint and ConnectionManager for real-time frontend telemetry."""

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger
from app.orchestrator.core import global_orchestrator
from app.orchestrator.models import OrchestratorEvent
from app.storage.event_store import StoredEvent, global_event_store

logger = get_logger("api.ws")
router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """Thread-safe WebSocket in-memory pub/sub broadcaster for real-time simulation events."""

    def __init__(self) -> None:
        self._active_connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    @property
    def connection_count(self) -> int:
        return len(self._active_connections)

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new active WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self._active_connections.add(websocket)
        logger.info(
            "WebSocket client connected",
            active_connections=len(self._active_connections),
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        """Unregister a disconnected WebSocket connection."""
        async with self._lock:
            self._active_connections.discard(websocket)
        logger.info(
            "WebSocket client disconnected",
            active_connections=len(self._active_connections),
        )

    async def broadcast_event(self, event: OrchestratorEvent | StoredEvent | dict[str, Any]) -> int:
        """Broadcast an event payload to all currently connected clients concurrently."""
        if isinstance(event, (OrchestratorEvent, StoredEvent)):
            payload = event.model_dump()
        else:
            payload = event

        async with self._lock:
            connections = list(self._active_connections)

        if not connections:
            return 0

        dead_connections: list[WebSocket] = []

        async def _send(ws: WebSocket) -> None:
            try:
                await ws.send_json(payload)
            except Exception as err:
                logger.debug(f"Failed to send to WebSocket client: {err}")
                dead_connections.append(ws)

        await asyncio.gather(*[_send(ws) for ws in connections], return_exceptions=True)

        # Cleanup any dead connections identified during broadcast
        if dead_connections:
            async with self._lock:
                for dead_ws in dead_connections:
                    self._active_connections.discard(dead_ws)

        return len(connections) - len(dead_connections)


# Global singleton connection manager
ws_manager = ConnectionManager()


# Register broadcaster callback with the global orchestrator
async def _orchestrator_event_bridge(event: OrchestratorEvent) -> None:
    # 1. Persist to SQLite event log (assigns global monotonic sequence number)
    stored = await global_event_store.append_event(event)
    # 2. Broadcast persisted event to connected WebSockets
    await ws_manager.broadcast_event(stored)


global_orchestrator.register_event_subscriber(_orchestrator_event_bridge)


@router.websocket("/ws/events")
@router.websocket("/ws/engagements/{engagement_id}")
async def websocket_events_endpoint(
    websocket: WebSocket,
    engagement_id: str | None = None,
    last_seen_seq: int = 0,
) -> None:
    """Real-time full-duplex WebSocket stream delivering sequenced simulation events to frontend clients."""
    await ws_manager.connect(websocket)

    # Send initial handshake / welcome event with recovered latest sequence
    latest_seq = await global_event_store.get_latest_seq()
    handshake_payload = {
        "event_type": "connection_established",
        "seq": latest_seq,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "engagement_id": engagement_id,
        "last_seen_seq": last_seen_seq,
        "payload": {
            "status": "CONNECTED",
            "message": "Subscribed to RedCell_OS real-time event bus",
            "latest_seq": latest_seq,
        },
    }

    try:
        await websocket.send_json(handshake_payload)

        # Listen for client heartbeat pings or inbound commands
        while True:
            data = await websocket.receive_text()
            # Handle client-side ping
            if data.strip().lower() == "ping":
                await websocket.send_text("pong")
            else:
                try:
                    logger.debug(
                        "Received WebSocket message from client",
                        data=data,
                        engagement_id=engagement_id,
                    )
                except Exception:
                    pass

    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as err:
        logger.warning(f"Unexpected WebSocket error: {err}")
        await ws_manager.disconnect(websocket)
