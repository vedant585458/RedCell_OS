"""REST API endpoints for engagement intake, scope management, and lifecycle queries."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.engagement import EngagementResponse
from app.repositories.unit_of_work import UnitOfWork
from app.services.intake import EngagementIntakeRequest, EngagementIntakeService
from app.storage.database import get_session_factory

router = APIRouter(prefix="/api/v1/engagements", tags=["engagements", "intake"])


def get_uow_dependency() -> async_sessionmaker[AsyncSession]:
    return get_session_factory()


@router.post("", response_model=EngagementResponse, status_code=status.HTTP_201_CREATED)
async def create_engagement(
    req: EngagementIntakeRequest,
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_uow_dependency),
) -> EngagementResponse:
    """Submit a new authorized security engagement with structured Rules of Engagement (ROE).

    Enforces mandatory machine-readable target allowlists, persists the engagement,
    records an immutable audit entry, and emits an `engagement_created` real-time event.
    """
    service = EngagementIntakeService(session_factory=session_factory)
    try:
        return await service.intake_engagement(req)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_err)
        ) from val_err


@router.get("", response_model=list[EngagementResponse])
async def list_engagements(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_uow_dependency),
) -> list[EngagementResponse]:
    """List all registered penetration testing engagements in reverse chronological order."""
    async with UnitOfWork(session_factory) as uow:
        return await uow.engagements.list_engagements(limit=limit, offset=offset)


@router.get("/{engagement_id}", response_model=EngagementResponse)
async def get_engagement(
    engagement_id: str,
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_uow_dependency),
) -> EngagementResponse:
    """Fetch complete engagement record with nested Scope allowlists and Rules of Engagement (ROE)."""
    async with UnitOfWork(session_factory) as uow:
        eng = await uow.engagements.get_engagement_response(engagement_id)
        if not eng:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Engagement '{engagement_id}' not found",
            )
        return eng
