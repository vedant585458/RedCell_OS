"""REST API endpoints for Task listing, multi-dimensional filtering, and admin manual overrides."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.audit import AuditEventCreateRequest
from app.domain.task import TaskResponse
from app.orchestrator.core import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork
from app.storage.database import get_session_factory
from app.tasks.state_machine import TaskLifecycleState

router = APIRouter(prefix="/api/v1/tasks", tags=["Tasks"])


class TaskManualOverrideRequest(BaseModel):
    """Payload for manual administrative/debug task status override."""

    status: str = Field(
        ...,
        description="Target lifecycle status (e.g. pending, ready, assigned, in_progress, blocked, review, completed, failed, cancelled)",
    )
    assigned_agent_id: str | None = Field(
        default=None,
        description="Optional agent reassignment ID",
    )
    reason: str = Field(
        default="Manual administrative override",
        description="Justification for manual status change",
    )
    admin_override: bool = Field(
        default=False,
        description="Explicit confirmation flag required for manual override",
    )
    actor_id: str = Field(
        default="admin_operator",
        description="Identifier of operator or admin performing override",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


def get_uow_dependency() -> async_sessionmaker[AsyncSession]:
    return get_session_factory()


@router.get("", response_model=list[TaskResponse])
@router.get("/", response_model=list[TaskResponse], include_in_schema=False)
async def list_tasks(
    department_id: str | None = Query(
        default=None, description="Filter tasks by executing department ID"
    ),
    task_status: str | None = Query(
        default=None, alias="status", description="Filter tasks by status"
    ),
    assigned_agent_id: str | None = Query(
        default=None, alias="agent_id", description="Filter tasks by assigned agent ID"
    ),
    engagement_id: str | None = Query(
        default=None, description="Filter tasks by parent engagement ID"
    ),
    priority: int | None = Query(
        default=None, ge=1, le=4, description="Filter tasks by priority level (1=LOW to 4=CRITICAL)"
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Pagination limit"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_uow_dependency),
) -> list[TaskResponse]:
    """List and filter tasks for dashboard views and 2D office visualization.

    Supports filtering across department, lifecycle status, assigned agent, engagement scope,
    and priority with zero N+1 database queries.
    """
    resolved_status = None
    if task_status:
        try:
            state_enum = TaskLifecycleState(task_status)
            resolved_status = state_enum.value
        except Exception:
            resolved_status = task_status

    async with UnitOfWork(session_factory) as uow:
        return await uow.tasks.list_tasks(
            department_id=department_id,
            status=resolved_status,
            assigned_agent_id=assigned_agent_id,
            engagement_id=engagement_id,
            priority=priority,
            limit=limit,
            offset=offset,
        )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_uow_dependency),
) -> TaskResponse:
    """Retrieve a single task by ID along with its prerequisite dependencies and blocked dependents."""
    async with UnitOfWork(session_factory) as uow:
        task = await uow.tasks.get_task_response(task_id)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task '{task_id}' not found",
            )
        return task


@router.patch("/{task_id}", response_model=TaskResponse)
async def manual_task_status_override(
    task_id: str,
    req: TaskManualOverrideRequest,
    x_admin_override: str | None = Header(
        default=None,
        alias="X-Admin-Override",
        description="Explicit header required to authorize manual status override ('true' or '1')",
    ),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_uow_dependency),
) -> TaskResponse:
    """Manual status override endpoint for administrative, operator intervention, and debug workflows.

    Technical Decision: Gated behind an explicit admin/debug confirmation flag (via 'X-Admin-Override: true'
    header or 'admin_override: true' body attribute) and strictly audited in the immutable audit log.
    """
    # 1. Verify admin/debug authorization gate
    header_confirmed = x_admin_override is not None and x_admin_override.lower() in (
        "true",
        "1",
        "yes",
    )
    body_confirmed = req.admin_override is True

    if not (header_confirmed or body_confirmed):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Manual task status override is restricted to admin/debug use. "
                "Must provide explicit confirmation: pass header 'X-Admin-Override: true' "
                "or include 'admin_override: true' in request payload."
            ),
        )

    # 2. Validate target status against lifecycle enum
    try:
        target_state = TaskLifecycleState(req.status)
        new_status_val = target_state.value.upper()
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid task status '{req.status}'. Must be one of: {[s.value for s in TaskLifecycleState]}",
        ) from err

    async with UnitOfWork(session_factory) as uow:
        # Check task existence
        existing_task = await uow.tasks.get_task_response(task_id)
        if not existing_task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task '{task_id}' not found",
            )

        prior_status = existing_task.status.value

        # 3. Update task in database
        updated_task = await uow.tasks.update_task(
            task_id=task_id,
            status=new_status_val,
            assigned_agent_id=req.assigned_agent_id,
        )
        if not updated_task:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update task '{task_id}'",
            )

        # 4. Append immutable audit event
        corr_id = f"corr-override-{task_id}-{uuid.uuid4().hex[:8]}"
        await uow.audit.append_audit_event(
            AuditEventCreateRequest(
                event_id=f"aud-override-{task_id}-{uuid.uuid4().hex[:8]}",
                engagement_id=existing_task.engagement_id or "system",
                correlation_id=corr_id,
                event_type="task_status_manually_overridden",
                actor_type="ADMIN",
                actor_id=req.actor_id,
                payload={
                    "task_id": task_id,
                    "prior_status": prior_status,
                    "new_status": new_status_val,
                    "assigned_agent_id": req.assigned_agent_id or existing_task.assigned_agent_id,
                    "reason": req.reason,
                    "actor_id": req.actor_id,
                    "admin_override": True,
                    "metadata": req.metadata,
                },
            )
        )
        await uow.commit()

    # 5. Emit event to orchestrator event stream for real-time WebSocket listeners
    await global_orchestrator.emit_event(
        event_type="task_status_changed",
        correlation_id=corr_id,
        engagement_id=existing_task.engagement_id,
        task_id=task_id,
        department_id=existing_task.department_id,
        agent_id=req.assigned_agent_id or existing_task.assigned_agent_id,
        payload={
            "task_id": task_id,
            "prior_status": prior_status,
            "new_status": new_status_val,
            "reason": req.reason,
            "manual_override": True,
            "actor_id": req.actor_id,
        },
    )

    return updated_task
