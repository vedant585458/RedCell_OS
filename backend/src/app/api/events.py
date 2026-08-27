"""REST API endpoint for event stream synchronization and replay-on-reconnect."""

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.storage.event_store import StoredEvent, global_event_store

router = APIRouter(prefix="/api/v1", tags=["events", "sync"])


class EventReplayResponse(BaseModel):
    """Response payload containing missed events for reconnect synchronization."""

    since_seq: int = Field(description="The sequence number requested as the threshold")
    latest_seq: int = Field(description="The highest sequence number available in the store")
    count: int = Field(description="Number of events returned in this batch")
    has_more: bool = Field(description="Whether more events remain beyond this batch limit")
    events: list[StoredEvent] = Field(description="Chronologically ordered events since threshold")


@router.get("/events", response_model=EventReplayResponse)
async def get_events_since(
    since: int = Query(
        default=0, ge=0, description="Sequence number threshold (returns events with seq > since)"
    ),
    limit: int = Query(
        default=500, ge=1, le=1000, description="Maximum number of events to return"
    ),
    engagement_id: str | None = Query(default=None, description="Optional engagement filter"),
) -> EventReplayResponse:
    """Retrieve chronologically ordered events emitted since a given sequence number.

    Used by reconnecting frontend clients to recover any missed events during temporary
    network disconnections without requiring a full page refresh or state reset.
    """
    events = await global_event_store.get_events_since(
        since_seq=since,
        limit=limit,
        engagement_id=engagement_id,
    )
    latest_seq = await global_event_store.get_latest_seq()
    has_more = len(events) == limit and (events[-1].seq < latest_seq if events else False)

    return EventReplayResponse(
        since_seq=since,
        latest_seq=latest_seq,
        count=len(events),
        has_more=has_more,
        events=events,
    )
