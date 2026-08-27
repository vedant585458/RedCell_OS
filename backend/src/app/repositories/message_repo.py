"""Concrete Message repository wrapping SQLAlchemy session."""

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.communication import (
    MessageCreateRequest,
    MessageModel,
    MessageResponse,
)
from app.repositories.base import BaseRepository


class MessageRepository(BaseRepository[MessageModel, str]):
    """Typed repository for Agent Message entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(MessageModel, session)

    async def send_message(self, req: MessageCreateRequest) -> MessageResponse:
        now = datetime.now(UTC).isoformat()
        model = MessageModel(
            id=req.id,
            engagement_id=req.engagement_id,
            sender_agent_id=req.sender_agent_id,
            recipient_agent_id=req.recipient_agent_id,
            task_id=req.task_id,
            message_type=req.message_type.value,
            content=req.content,
            metadata_json=json.dumps(req.metadata),
            created_at=now,
        )
        self.session.add(model)
        await self.session.flush()
        return model.to_response()

    async def list_by_task(self, task_id: str) -> list[MessageResponse]:
        stmt = (
            select(MessageModel)
            .where(MessageModel.task_id == task_id)
            .order_by(MessageModel.created_at.asc())
        )
        res = await self.session.execute(stmt)
        return [row.to_response() for row in res.scalars()]

    async def list_by_engagement(self, engagement_id: str) -> list[MessageResponse]:
        stmt = (
            select(MessageModel)
            .where(MessageModel.engagement_id == engagement_id)
            .order_by(MessageModel.created_at.asc())
        )
        res = await self.session.execute(stmt)
        return [row.to_response() for row in res.scalars()]
