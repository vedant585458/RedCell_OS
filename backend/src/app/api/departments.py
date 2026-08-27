"""REST API endpoints for department task queues, capacity, and status aggregations."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.task import TaskResponse, TaskStatus
from app.repositories.unit_of_work import UnitOfWork
from app.storage.database import get_session_factory

router = APIRouter(prefix="/api/v1/departments", tags=["departments", "task-queues"])


class DepartmentTaskStatusCounts(BaseModel):
    """Aggregated count of tasks by lifecycle status computed at database level."""

    pending: int = Field(default=0)
    ready: int = Field(default=0)
    in_progress: int = Field(default=0)
    awaiting_approval: int = Field(default=0)
    completed: int = Field(default=0)
    failed: int = Field(default=0)
    blocked: int = Field(default=0)
    total: int = Field(default=0)


class DepartmentTaskQueueResponse(BaseModel):
    """Department-scoped task queue response for dashboard and office visualization."""

    department_id: str
    department_name: str
    engagement_id: str | None
    counts: DepartmentTaskStatusCounts
    tasks: list[TaskResponse] = Field(default_factory=list)


class DepartmentTaskSummaryItem(BaseModel):
    """Summary item for a single department's queue health."""

    department_id: str
    department_name: str
    color_theme: str
    counts: DepartmentTaskStatusCounts


class AllDepartmentsSummaryResponse(BaseModel):
    """High-level summary of task distribution across all departments."""

    engagement_id: str | None
    total_active_tasks: int
    departments: list[DepartmentTaskSummaryItem]


def get_uow_dependency() -> async_sessionmaker[AsyncSession]:
    return get_session_factory()


@router.get("/{department_id}/tasks", response_model=DepartmentTaskQueueResponse)
async def get_department_task_queue(
    department_id: str,
    engagement_id: str | None = Query(default=None, description="Optional engagement filter"),
    task_status: TaskStatus | None = Query(
        default=None, alias="status", description="Optional status filter"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_uow_dependency),
) -> DepartmentTaskQueueResponse:
    """Retrieve the scoped task queue and SQL-aggregated status counts for a specific department.

    Used by the 2D office simulation to render department desk workloads, kanban boards,
    and agent activity queues with zero N+1 query overhead.
    """
    async with UnitOfWork(session_factory) as uow:
        dept = await uow.departments.get_by_id(department_id)
        if not dept:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Department '{department_id}' not found",
            )

        # 1. SQL-level status count aggregation
        raw_counts = await uow.tasks.get_department_task_counts(
            department_id=department_id,
            engagement_id=engagement_id,
        )
        counts = DepartmentTaskStatusCounts(**raw_counts)

        # 2. Paginated task items
        tasks = await uow.tasks.list_by_department(
            department_id=department_id,
            engagement_id=engagement_id,
            status=task_status,
            limit=limit,
            offset=offset,
        )

        return DepartmentTaskQueueResponse(
            department_id=dept.id,
            department_name=dept.name,
            engagement_id=engagement_id,
            counts=counts,
            tasks=tasks,
        )


@router.get("/tasks/summary", response_model=AllDepartmentsSummaryResponse)
async def get_all_departments_task_summary(
    engagement_id: str | None = Query(default=None, description="Optional engagement filter"),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_uow_dependency),
) -> AllDepartmentsSummaryResponse:
    """Retrieve aggregated task counts across all departments for high-level operations monitoring."""
    async with UnitOfWork(session_factory) as uow:
        depts = await uow.departments.list_departments()
        summary_items: list[DepartmentTaskSummaryItem] = []
        total_active = 0

        for d in depts:
            raw_counts = await uow.tasks.get_department_task_counts(
                department_id=d.id,
                engagement_id=engagement_id,
            )
            counts = DepartmentTaskStatusCounts(**raw_counts)
            total_active += counts.in_progress + counts.ready + counts.awaiting_approval

            summary_items.append(
                DepartmentTaskSummaryItem(
                    department_id=d.id,
                    department_name=d.name,
                    color_theme=d.color_theme,
                    counts=counts,
                )
            )

        return AllDepartmentsSummaryResponse(
            engagement_id=engagement_id,
            total_active_tasks=total_active,
            departments=summary_items,
        )
