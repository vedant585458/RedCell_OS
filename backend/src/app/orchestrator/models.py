"""Data models and commands for the Orchestrator loop."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class OrchestratorState(StrEnum):
    """Lifecycle states of the central Orchestrator."""

    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    ERROR = "ERROR"


class OrchestratorCommand(BaseModel):
    """Inbound command submitted to the orchestrator command queue."""

    command_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    command_type: str = Field(
        ...,
        description="Action type (e.g. START_ENGAGEMENT, APPROVE_GATE, KILL_SWITCH)",
    )
    correlation_id: str = Field(default_factory=lambda: f"corr-{uuid.uuid4().hex[:12]}")
    payload: dict[str, Any] = Field(default_factory=dict, description="Command payload parameters")
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class OrchestratorEvent(BaseModel):
    """Outbound event emitted by the orchestrator event bus."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    seq: int = Field(default=0, description="Monotonically increasing sequence number")
    event_type: str = Field(..., description="Event categorical name")
    correlation_id: str = Field(..., description="Correlation ID for trace linking")
    engagement_id: str | None = Field(default=None)
    agent_id: str | None = Field(default=None)
    department_id: str | None = Field(default=None)
    task_id: str | None = Field(default=None)
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
