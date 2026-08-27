"""Append-only SQLite event log with monotonic sequence numbers and crash-resilient replay support."""

import asyncio
import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import get_logger
from app.orchestrator.models import OrchestratorEvent

logger = get_logger("storage.event_store")


class StoredEvent(BaseModel):
    """Event model persisted in SQLite append-only log."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    seq: int = Field(description="Global monotonic sequence number")
    event_type: str
    correlation_id: str
    engagement_id: str | None = None
    agent_id: str | None = None
    department_id: str | None = None
    task_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class EventStore:
    """Thread-safe, crash-resilient SQLite event store enforcing global monotonic sequence ordering."""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path:
            self.db_path = db_path
        else:
            data_dir = os.path.abspath(settings.data_dir)
            os.makedirs(data_dir, exist_ok=True)
            self.db_path = os.path.join(data_dir, "redcell_events.db")

        self._lock = asyncio.Lock()
        self._seq_counter = 0
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create an optimized SQLite connection with WAL mode enabled."""
        conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def _init_db(self) -> None:
        """Initialize the append-only event schema and recover the highest sequence number."""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stored_events (
                    id TEXT PRIMARY KEY,
                    seq INTEGER NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    engagement_id TEXT,
                    agent_id TEXT,
                    department_id TEXT,
                    task_id TEXT,
                    payload_json TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_seq ON stored_events (seq ASC);")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_eng_seq ON stored_events (engagement_id, seq ASC);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_corr ON stored_events (correlation_id);"
            )

            # Recover maximum sequence counter to prevent resets on restart
            cursor = conn.execute("SELECT COALESCE(MAX(seq), 0) as max_seq FROM stored_events;")
            row = cursor.fetchone()
            self._seq_counter = int(row["max_seq"]) if row else 0

        logger.info(
            "EventStore initialized",
            db_path=self.db_path,
            latest_recovered_seq=self._seq_counter,
        )

    async def get_latest_seq(self) -> int:
        """Return the current global maximum sequence number."""
        async with self._lock:
            return self._seq_counter

    async def append_event(self, event: OrchestratorEvent | StoredEvent) -> StoredEvent:
        """Persist an event to the append-only table and allocate the next monotonic sequence number."""
        async with self._lock:
            self._seq_counter += 1
            seq = self._seq_counter

            stored = StoredEvent(
                id=str(uuid.uuid4()),
                seq=seq,
                event_type=event.event_type,
                correlation_id=event.correlation_id,
                engagement_id=event.engagement_id,
                agent_id=event.agent_id,
                department_id=event.department_id,
                task_id=event.task_id,
                payload=event.payload,
                timestamp_utc=event.timestamp_utc or datetime.now(UTC).isoformat(),
            )

            # Run SQLite insert in thread pool to avoid blocking asyncio event loop
            def _insert() -> None:
                with self._get_connection() as conn:
                    conn.execute(
                        """
                        INSERT INTO stored_events (
                            id, seq, event_type, correlation_id, engagement_id,
                            agent_id, department_id, task_id, payload_json, timestamp_utc
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            stored.id,
                            stored.seq,
                            stored.event_type,
                            stored.correlation_id,
                            stored.engagement_id,
                            stored.agent_id,
                            stored.department_id,
                            stored.task_id,
                            json.dumps(stored.payload),
                            stored.timestamp_utc,
                        ),
                    )

            await asyncio.to_thread(_insert)
            return stored

    async def get_events_since(
        self,
        since_seq: int = 0,
        limit: int = 500,
        engagement_id: str | None = None,
    ) -> list[StoredEvent]:
        """Fetch sequenced events greater than `since_seq` for gap recovery and client replay."""

        def _query() -> list[StoredEvent]:
            with self._get_connection() as conn:
                if engagement_id:
                    cursor = conn.execute(
                        """
                        SELECT * FROM stored_events
                        WHERE seq > ? AND (engagement_id = ? OR engagement_id IS NULL)
                        ORDER BY seq ASC
                        LIMIT ?;
                        """,
                        (since_seq, engagement_id, limit),
                    )
                else:
                    cursor = conn.execute(
                        """
                        SELECT * FROM stored_events
                        WHERE seq > ?
                        ORDER BY seq ASC
                        LIMIT ?;
                        """,
                        (since_seq, limit),
                    )

                results: list[StoredEvent] = []
                for row in cursor.fetchall():
                    try:
                        payload = json.loads(row["payload_json"])
                    except Exception:
                        payload = {}

                    results.append(
                        StoredEvent(
                            id=row["id"],
                            seq=row["seq"],
                            event_type=row["event_type"],
                            correlation_id=row["correlation_id"],
                            engagement_id=row["engagement_id"],
                            agent_id=row["agent_id"],
                            department_id=row["department_id"],
                            task_id=row["task_id"],
                            payload=payload,
                            timestamp_utc=row["timestamp_utc"],
                        )
                    )
                return results

        return await asyncio.to_thread(_query)


# Global singleton event store instance
global_event_store = EventStore()
