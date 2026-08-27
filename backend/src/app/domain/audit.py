"""Immutable Audit Event domain models and append-only cryptographic verification repository."""

import json
import uuid
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.engagement import Base


class ImmutableAuditViolationError(RuntimeError):
    """Raised whenever an update or delete operation is attempted on immutable audit records."""

    pass


class AuditEventCreateRequest(BaseModel):
    """Payload to record an immutable audit event in the cryptographic event log."""

    event_id: str = Field(default_factory=lambda: f"audit-{uuid.uuid4().hex[:12]}")
    engagement_id: str
    correlation_id: str
    event_type: str
    actor_type: str = Field(default="AGENT", description="AGENT | OPERATOR | SYSTEM")
    actor_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class AuditEventResponse(BaseModel):
    """Outbound API response representing an immutable audit log entry."""

    event_id: str
    seq: int
    engagement_id: str
    correlation_id: str
    event_type: str
    actor_type: str
    actor_id: str
    payload: dict[str, Any]
    prev_event_hash: str
    event_hash: str
    created_at: str


class AuditEventModel(Base):
    """SQLAlchemy relational table mapping for Immutable Audit Events."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    engagement_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("engagements.id"), nullable=False, index=True
    )
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False, default="AGENT")
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)

    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    prev_event_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="0" * 64)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)

    def to_response(self) -> AuditEventResponse:
        try:
            payload = json.loads(str(self.payload_json))
        except Exception:
            payload = {}

        return AuditEventResponse(
            event_id=str(self.id),
            seq=int(self.seq),
            engagement_id=str(self.engagement_id),
            correlation_id=str(self.correlation_id),
            event_type=str(self.event_type),
            actor_type=str(self.actor_type),
            actor_id=str(self.actor_id),
            payload=payload,
            prev_event_hash=str(self.prev_event_hash),
            event_hash=str(self.event_hash),
            created_at=str(self.created_at),
        )


class ImmutableAuditEventRepository:
    """Repository strictly enforcing append-only immutability and cryptographic hash chaining for audit logs."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    async def append(self, req: AuditEventCreateRequest) -> AuditEventResponse:
        """Append a new audit event, calculating SHA-256 hash link with preceding event."""
        now = datetime.now(UTC).isoformat()
        payload_str = json.dumps(req.payload, sort_keys=True)

        async with self.session_factory() as session:
            async with session.begin():
                from sqlalchemy import select

                # 1. Fetch the latest event to obtain the preceding hash and seq counter
                stmt = select(AuditEventModel).order_by(AuditEventModel.seq.desc()).limit(1)
                res = await session.execute(stmt)
                last_event = res.scalar_one_or_none()

                if last_event:
                    next_seq = int(last_event.seq) + 1
                    prev_hash = str(last_event.event_hash)
                else:
                    next_seq = 1
                    prev_hash = "0" * 64  # Genesis root hash

                # 2. Compute cryptographic SHA-256 integrity hash
                hash_input = f"{next_seq}:{req.engagement_id}:{req.event_type}:{prev_hash}:{payload_str}:{now}"
                event_hash = sha256(hash_input.encode("utf-8")).hexdigest()

                model = AuditEventModel(
                    id=req.event_id,
                    seq=next_seq,
                    engagement_id=req.engagement_id,
                    correlation_id=req.correlation_id,
                    event_type=req.event_type,
                    actor_type=req.actor_type,
                    actor_id=req.actor_id,
                    payload_json=payload_str,
                    prev_event_hash=prev_hash,
                    event_hash=event_hash,
                    created_at=now,
                )
                session.add(model)
            await session.commit()
            return model.to_response()

    async def get_by_seq(self, seq: int) -> AuditEventResponse | None:
        async with self.session_factory() as session:
            from sqlalchemy import select

            stmt = select(AuditEventModel).where(AuditEventModel.seq == seq)
            res = await session.execute(stmt)
            model = res.scalar_one_or_none()
            return model.to_response() if model else None

    async def list_by_engagement(
        self, engagement_id: str, since_seq: int = 0
    ) -> list[AuditEventResponse]:
        async with self.session_factory() as session:
            from sqlalchemy import select

            stmt = (
                select(AuditEventModel)
                .where(AuditEventModel.engagement_id == engagement_id)
                .where(AuditEventModel.seq > since_seq)
                .order_by(AuditEventModel.seq.asc())
            )
            res = await session.execute(stmt)
            return [row.to_response() for row in res.scalars()]

    async def verify_integrity(self, engagement_id: str) -> tuple[bool, str]:
        """Verify the cryptographic SHA-256 Merkle chain integrity of all events in the engagement."""
        events = await self.list_by_engagement(engagement_id)
        if not events:
            return True, "No audit events recorded."

        expected_prev_hash = "0" * 64
        for idx, event in enumerate(events):
            if idx > 0 and event.prev_event_hash != expected_prev_hash:
                return False, f"Broken hash chain at sequence {event.seq}: prev_hash mismatch."

            payload_str = json.dumps(event.payload, sort_keys=True)
            recalculated_input = f"{event.seq}:{event.engagement_id}:{event.event_type}:{event.prev_event_hash}:{payload_str}:{event.created_at}"
            recalculated_hash = sha256(recalculated_input.encode("utf-8")).hexdigest()

            if recalculated_hash != event.event_hash:
                return (
                    False,
                    f"Tampered audit record detected at sequence {event.seq}: payload hash mismatch.",
                )

            expected_prev_hash = event.event_hash

        return True, f"Cryptographic audit chain verified cleanly across {len(events)} events."

    # Explicitly forbidden operations to guarantee immutable append-only enforcement
    async def update(self, *args: Any, **kwargs: Any) -> None:
        raise ImmutableAuditViolationError(
            "Audit records are cryptographically immutable and append-only. Modification is strictly forbidden."
        )

    async def delete(self, *args: Any, **kwargs: Any) -> None:
        raise ImmutableAuditViolationError(
            "Audit records are cryptographically immutable and append-only. Deletion is strictly forbidden."
        )
