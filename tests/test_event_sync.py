"""Integration tests for event sequence numbers, SQLite persistence, and REST replay-on-reconnect."""

import os

import pytest
from app.main import create_app
from app.orchestrator.models import OrchestratorEvent
from app.storage.event_store import EventStore
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_event_store_monotonic_sequences(tmp_path):
    db_file = os.path.join(tmp_path, "test_events.db")
    store = EventStore(db_path=db_file)

    assert await store.get_latest_seq() == 0

    e1 = await store.append_event(
        OrchestratorEvent(
            event_type="scan_started",
            correlation_id="c1",
            payload={"target": "10.0.0.1"},
        )
    )
    e2 = await store.append_event(
        OrchestratorEvent(
            event_type="port_found", correlation_id="c1", payload={"port": 80}
        )
    )
    e3 = await store.append_event(
        OrchestratorEvent(
            event_type="scan_finished", correlation_id="c1", payload={"status": "done"}
        )
    )

    assert e1.seq == 1
    assert e2.seq == 2
    assert e3.seq == 3
    assert await store.get_latest_seq() == 3


@pytest.mark.asyncio
async def test_event_store_sequence_preservation_across_restarts(tmp_path):
    db_file = os.path.join(tmp_path, "restart_test.db")

    # Phase 1: Store 5 events before simulated crash/restart
    store1 = EventStore(db_path=db_file)
    for i in range(5):
        await store1.append_event(
            OrchestratorEvent(event_type=f"event_{i}", correlation_id="c_init")
        )
    assert await store1.get_latest_seq() == 5

    # Phase 2: Simulate process restart by creating fresh EventStore instance pointing to same SQLite DB
    store2 = EventStore(db_path=db_file)
    assert await store2.get_latest_seq() == 5  # Must not reset to 0!

    # Phase 3: Next append must allocate seq = 6
    e_next = await store2.append_event(
        OrchestratorEvent(event_type="event_post_restart", correlation_id="c_restart")
    )
    assert e_next.seq == 6
    assert await store2.get_latest_seq() == 6


@pytest.mark.asyncio
async def test_get_events_since_query(tmp_path):
    db_file = os.path.join(tmp_path, "replay_query.db")
    store = EventStore(db_path=db_file)

    for i in range(1, 11):
        await store.append_event(
            OrchestratorEvent(
                event_type=f"evt_{i}",
                correlation_id="corr_batch",
                engagement_id="eng-target-01" if i <= 7 else "eng-target-02",
            )
        )

    # Query events since seq = 6 (should return 7, 8, 9, 10)
    missed = await store.get_events_since(since_seq=6)
    assert len(missed) == 4
    assert [e.seq for e in missed] == [7, 8, 9, 10]

    # Query scoped to engagement
    eng1_missed = await store.get_events_since(
        since_seq=3, engagement_id="eng-target-01"
    )
    assert len(eng1_missed) == 4
    assert [e.seq for e in eng1_missed] == [4, 5, 6, 7]


def test_rest_events_replay_endpoint():
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/v1/events?since=0&limit=100")
    assert response.status_code == 200
    data = response.json()
    assert "since_seq" in data
    assert "latest_seq" in data
    assert "count" in data
    assert "events" in data
    assert isinstance(data["events"], list)
