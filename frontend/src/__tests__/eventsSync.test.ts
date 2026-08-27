import { describe, it, expect, vi, beforeEach } from "vitest";
import { eventSyncManager } from "../api/eventsSync";
import { useEventStore } from "../state/eventStore";
import { apiClient } from "../api/client";
import { RedCellEvent } from "../types/events";

describe("EventSyncManager Reconnect Replay", () => {
  beforeEach(() => {
    useEventStore.getState().reset();
    vi.restoreAllMocks();
  });

  it("recovers missed events during disconnection gap via REST replay", async () => {
    // Initial state: client saw up to sequence 2
    useEventStore.setState({ lastSeenSeq: 2 });

    const mockMissedEvents: RedCellEvent[] = [
      {
        seq_num: 3,
        event_type: "port_scanned",
        correlation_id: "c1",
        engagement_id: "eng-01",
        timestamp_utc: new Date().toISOString(),
        payload: { port: 8088 },
      },
      {
        seq_num: 4,
        event_type: "vulnerability_found",
        correlation_id: "c1",
        engagement_id: "eng-01",
        timestamp_utc: new Date().toISOString(),
        payload: { cve: "CVE-2026-9999" },
      },
    ];

    vi.spyOn(apiClient, "get").mockResolvedValue({
      since_seq: 2,
      latest_seq: 4,
      count: 2,
      has_more: false,
      events: mockMissedEvents,
    });

    const recoveredCount = await eventSyncManager.syncMissedEvents("eng-01");

    expect(recoveredCount).toBe(2);
    expect(useEventStore.getState().lastSeenSeq).toBe(4);
    expect(useEventStore.getState().events.length).toBe(2);
    expect(useEventStore.getState().events[0].seq_num).toBe(3);
    expect(useEventStore.getState().events[1].seq_num).toBe(4);
  });

  it("ignores duplicate stale live events from WebSocket with seq <= lastSeenSeq", () => {
    useEventStore.setState({ lastSeenSeq: 10 });

    const staleEvent: RedCellEvent = {
      seq_num: 8, // Stale!
      event_type: "agent_state_changed",
      correlation_id: "c_old",
      engagement_id: "eng-01",
      timestamp_utc: new Date().toISOString(),
      payload: {},
    };

    eventSyncManager.handleLiveEvent(staleEvent);

    // Should NOT have applied stale event
    expect(useEventStore.getState().events.length).toBe(0);
    expect(useEventStore.getState().lastSeenSeq).toBe(10);
  });

  it("applies fresh live event with seq > lastSeenSeq immediately", () => {
    useEventStore.setState({ lastSeenSeq: 10 });

    const freshEvent: RedCellEvent = {
      seq_num: 11,
      event_type: "approval_requested",
      correlation_id: "c_fresh",
      engagement_id: "eng-01",
      timestamp_utc: new Date().toISOString(),
      payload: { gate_id: "gate-01" },
    };

    eventSyncManager.handleLiveEvent(freshEvent);

    expect(useEventStore.getState().events.length).toBe(1);
    expect(useEventStore.getState().lastSeenSeq).toBe(11);
  });
});
