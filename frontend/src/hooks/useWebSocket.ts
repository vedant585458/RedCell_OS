import { useEffect, useRef } from "react";
import { useEventStore } from "../state/eventStore";
import { eventSyncManager } from "../api/eventsSync";
import { getWebSocketUrl } from "../config";
import { RedCellEvent } from "../types/events";

export function useWebSocket(engagementId: string | null) {
  const setConnected = useEventStore((state) => state.setConnected);
  const lastSeenSeq = useEventStore((state) => state.lastSeenSeq);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!engagementId) return;

    const url = getWebSocketUrl(engagementId, lastSeenSeq);
    const ws = new WebSocket(url);
    socketRef.current = ws;

    ws.onopen = async () => {
      setConnected(true);
      // Synchronize any events that occurred while client was disconnected
      await eventSyncManager.syncMissedEvents(engagementId);
    };

    ws.onmessage = (event) => {
      try {
        const payload: RedCellEvent = JSON.parse(event.data);
        eventSyncManager.handleLiveEvent(payload);
      } catch (err) {
        console.error("Failed to parse WebSocket event:", err);
      }
    };

    ws.onclose = () => {
      setConnected(false);
    };

    ws.onerror = (err) => {
      console.error("WebSocket encountered error:", err);
      setConnected(false);
    };

    return () => {
      ws.close();
    };
  }, [engagementId, lastSeenSeq, setConnected]);
}
