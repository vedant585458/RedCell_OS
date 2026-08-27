"""Concrete Engagement repository wrapping SQLAlchemy session."""

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.engagement import (
    EngagementCreateRequest,
    EngagementModel,
    EngagementResponse,
)
from app.repositories.base import BaseRepository


class EngagementRepository(BaseRepository[EngagementModel, str]):
    """Typed repository for Engagement operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(EngagementModel, session)

    async def create_engagement(self, req: EngagementCreateRequest) -> EngagementResponse:
        now = datetime.now(UTC).isoformat()
        model = EngagementModel(
            id=req.engagement_id,
            title=req.title,
            status="CREATED",
            organization=req.organization,
            authorized_by=req.authorized_by,
            operator_id=req.operator_id,
            valid_from_utc=req.time_window.valid_from_utc,
            valid_until_utc=req.time_window.valid_until_utc,
            timezone=req.time_window.timezone,
            emergency_freeze="true" if req.time_window.emergency_freeze else "false",
            target_scope_json=json.dumps(req.target_scope.model_dump()),
            rules_of_engagement_json=json.dumps(req.rules_of_engagement.model_dump()),
            created_at=now,
            updated_at=now,
        )
        self.session.add(model)
        await self.session.flush()
        return model.to_response()

    async def get_engagement_response(self, engagement_id: str) -> EngagementResponse | None:
        model = await self.get_by_id(engagement_id)
        return model.to_response() if model else None

    async def list_engagements(self, limit: int = 100, offset: int = 0) -> list[EngagementResponse]:
        stmt = (
            select(EngagementModel)
            .order_by(EngagementModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        res = await self.session.execute(stmt)
        return [row.to_response() for row in res.scalars()]

    async def update_status(self, engagement_id: str, status: str) -> EngagementResponse | None:
        model = await self.get_by_id(engagement_id)
        if not model:
            return None
        model.status = status
        model.updated_at = datetime.now(UTC).isoformat()
        await self.session.flush()
        return model.to_response()
