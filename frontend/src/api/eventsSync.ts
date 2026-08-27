/**
 * Event Synchronization and Replay-on-Reconnect Manager for RedCell_OS Frontend
 */

import { apiClient } from "./client";
import { useEventStore } from "../state/eventStore";
import { eventBus } from "../state/eventBus";
import { RedCellEvent } from "../types/events";

export interface EventReplayResponse {
  since_seq: number;
  latest_seq: number;
  count: number;
  has_more: boolean;
  events: RedCellEvent[];
}

export class EventSyncManager {
  private isCatchingUp: boolean = false;
  private pendingLiveEvents: RedCellEvent[] = [];

  /**
   * Fetch and apply all missed events from the backend REST replay endpoint.
   * Ensures the frontend Zustand store achieves 100% state consistency on reconnect.
   */
  public async syncMissedEvents(engagementId?: string): Promise<number> {
    const lastSeenSeq = useEventStore.getState().lastSeenSeq;
    this.isCatchingUp = true;
    let totalRecovered = 0;
    let currentSince = lastSeenSeq;
    let hasMore = true;

    try {
      while (hasMore) {
        const response: EventReplayResponse = await apiClient.get<EventReplayResponse>(
          "/api/v1/events",
          {
            params: {
              since: currentSince,
              limit: 500,
              engagement_id: engagementId,
            },
          }
        );

        if (!response.events || response.events.length === 0) {
          break;
        }

        for (const event of response.events) {
          const rawSeq = event.seq_num ?? (event as unknown as { seq: number }).seq ?? 0;
          const normalizedEvent: RedCellEvent = {
            ...event,
            seq_num: rawSeq,
          };

          if (normalizedEvent.seq_num > useEventStore.getState().lastSeenSeq) {
            // Dispatch through event bus to update all normalized domain entity tables
            eventBus.dispatch(normalizedEvent);
            totalRecovered++;
          }
          currentSince = Math.max(currentSince, normalizedEvent.seq_num);
        }

        hasMore = response.has_more;
      }

      // Flush any live events buffered while REST catch-up was in progress
      for (const liveEvent of this.pendingLiveEvents) {
        if (liveEvent.seq_num > useEventStore.getState().lastSeenSeq) {
          eventBus.dispatch(liveEvent);
        }
      }
      this.pendingLiveEvents = [];
    } catch (err) {
      console.error("Failed to sync missed events from backend:", err);
    } finally {
      this.isCatchingUp = false;
    }

    return totalRecovered;
  }

  /**
   * Process a live incoming event from the WebSocket stream.
   * If catch-up is in progress, buffers the event; otherwise validates sequence and dispatches immediately.
   */
  public handleLiveEvent(event: RedCellEvent): void {
    const rawSeq = event.seq_num ?? (event as unknown as { seq: number }).seq ?? 0;
    const normalizedEvent: RedCellEvent = {
      ...event,
      seq_num: rawSeq,
    };

    if (this.isCatchingUp) {
      this.pendingLiveEvents.push(normalizedEvent);
      return;
    }

    // Drop stale duplicates
    if (normalizedEvent.seq_num > 0 && normalizedEvent.seq_num <= useEventStore.getState().lastSeenSeq) {
      return;
    }

    eventBus.dispatch(normalizedEvent);
  }
}

export const eventSyncManager = new EventSyncManager();
export default eventSyncManager;
