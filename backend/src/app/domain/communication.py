"""Agent-to-agent communication and messaging domain models."""

import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.engagement import Base


class MessageType(StrEnum):
    """Types of inter-agent messages."""

    TASK_HANDOFF = "TASK_HANDOFF"
    BRIEFING = "BRIEFING"
    STATUS_UPDATE = "STATUS_UPDATE"
    ALERT = "ALERT"
    QUERY = "QUERY"


class MessageCreateRequest(BaseModel):
    """Payload to dispatch an agent message."""

    id: str = Field(default_factory=lambda: f"msg-{uuid.uuid4().hex[:8]}")
    engagement_id: str = Field(..., description="Parent engagement identifier")
    sender_agent_id: str = Field(..., description="Originating agent ID")
    recipient_agent_id: str | None = Field(
        default=None, description="Target agent ID, or None for broadcast"
    )
    task_id: str | None = Field(default=None)
    message_type: MessageType = Field(default=MessageType.STATUS_UPDATE)
    content: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageResponse(BaseModel):
    """Outbound API response representing an agent message."""

    id: str
    engagement_id: str
    sender_agent_id: str
    recipient_agent_id: str | None
    task_id: str | None
    message_type: MessageType
    content: str
    metadata: dict[str, Any]
    created_at: str


class MessageModel(Base):
    """SQLAlchemy relational table mapping for Agent Messages."""

    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    engagement_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("engagements.id"), nullable=False, index=True
    )
    sender_agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_employees.id"), nullable=False, index=True
    )
    recipient_agent_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("ai_employees.id"), nullable=True, index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("tasks.id"), nullable=True, index=True
    )

    message_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=MessageType.STATUS_UPDATE.value
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)

    def to_response(self) -> MessageResponse:
        try:
            meta = json.loads(str(self.metadata_json))
        except Exception:
            meta = {}

        return MessageResponse(
            id=str(self.id),
            engagement_id=str(self.engagement_id),
            sender_agent_id=str(self.sender_agent_id),
            recipient_agent_id=str(self.recipient_agent_id) if self.recipient_agent_id else None,
            task_id=str(self.task_id) if self.task_id else None,
            message_type=MessageType(str(self.message_type)),
            content=str(self.content),
            metadata=meta,
            created_at=str(self.created_at),
        )


class MessageRepository:
    """Repository handling CRUD and message queries between agents."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    async def send_message(self, req: MessageCreateRequest) -> MessageResponse:
        """Create and persist an inter-agent message."""
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

        async with self.session_factory() as session:
            async with session.begin():
                session.add(model)
            await session.commit()
            return model.to_response()

    async def list_by_engagement(self, engagement_id: str) -> list[MessageResponse]:
        """List all messages within an engagement in chronological order."""
        async with self.session_factory() as session:
            from sqlalchemy import select

            stmt = (
                select(MessageModel)
                .where(MessageModel.engagement_id == engagement_id)
                .order_by(MessageModel.created_at.asc())
            )
            res = await session.execute(stmt)
            return [row.to_response() for row in res.scalars()]

    async def list_by_task(self, task_id: str) -> list[MessageResponse]:
        """List messages relevant to a specific task."""
        async with self.session_factory() as session:
            from sqlalchemy import select

            stmt = (
                select(MessageModel)
                .where(MessageModel.task_id == task_id)
                .order_by(MessageModel.created_at.asc())
            )
            res = await session.execute(stmt)
            return [row.to_response() for row in res.scalars()]
