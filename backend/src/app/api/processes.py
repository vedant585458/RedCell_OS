"""REST API endpoints for process registry inspection and emergency kill switch."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.process.registry import ProcessRecord, global_process_registry

router = APIRouter(prefix="/api/v1", tags=["processes", "kill-switch"])


class KillSwitchRequest(BaseModel):
    """Payload for emergency kill-switch requests."""

    engagement_id: str | None = Field(
        default=None, description="Optional target engagement to isolate"
    )
    agent_id: str | None = Field(default=None, description="Optional target agent to isolate")


class KillSwitchResponse(BaseModel):
    """Response payload returned after kill switch execution."""

    success: bool
    processes_killed: int
    scope: str
    message: str


@router.get("/processes", response_model=list[ProcessRecord])
async def list_active_processes() -> list[ProcessRecord]:
    """List all currently active worker subprocesses supervised by the registry."""
    return await global_process_registry.list_active()


@router.post("/processes/{process_id}/kill", response_model=dict[str, Any])
async def kill_process_by_id(process_id: str) -> dict[str, Any]:
    """Kill a single running worker process immediately."""
    success = await global_process_registry.kill_process(process_id)
    if not success:
        raise HTTPException(
            status_code=404, detail=f"Process '{process_id}' not found or already terminated"
        )
    return {"success": True, "process_id": process_id, "status": "KILLED"}


@router.post("/kill-switch", response_model=KillSwitchResponse)
async def trigger_emergency_kill_switch(
    payload: KillSwitchRequest | None = None,
) -> KillSwitchResponse:
    """Execute immediate emergency kill switch (< 200ms) for global, engagement, or agent scope."""
    if payload and payload.agent_id:
        killed = await global_process_registry.kill_all_for_agent(payload.agent_id)
        scope = f"agent:{payload.agent_id}"
    elif payload and payload.engagement_id:
        killed = await global_process_registry.kill_all_for_engagement(payload.engagement_id)
        scope = f"engagement:{payload.engagement_id}"
    else:
        killed = await global_process_registry.kill_all_global()
        scope = "global"

    return KillSwitchResponse(
        success=True,
        processes_killed=killed,
        scope=scope,
        message=f"Emergency kill switch executed for scope '{scope}'. Terminated {killed} processes.",
    )
