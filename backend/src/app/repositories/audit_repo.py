"""Immutable AuditEvent repository enforcing append-only cryptographically chained records."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.audit import (
    AuditEventCreateRequest,
    AuditEventModel,
    AuditEventResponse,
    ImmutableAuditViolationError,
)
from app.repositories.base import BaseRepository


class AuditRepository(BaseRepository[AuditEventModel, str]):
    """Strictly immutable append-only repository for Audit Events."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(AuditEventModel, session)

    async def append_audit_event(self, req: AuditEventCreateRequest) -> AuditEventResponse:
        now = datetime.now(UTC).isoformat()
        payload_str = json.dumps(req.payload, sort_keys=True)

        # 1. Fetch the latest sequence number and previous event hash
        stmt = select(AuditEventModel).order_by(AuditEventModel.seq.desc()).limit(1)
        res = await self.session.execute(stmt)
        last_event = res.scalar_one_or_none()

        if last_event:
            next_seq = int(last_event.seq) + 1
            prev_hash = str(last_event.event_hash)
        else:
            next_seq = 1
            prev_hash = "0" * 64

        # 2. Compute SHA-256 Merkle chain integrity hash
        hash_input = (
            f"{next_seq}:{req.engagement_id}:{req.event_type}:{prev_hash}:{payload_str}:{now}"
        )
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
        self.session.add(model)
        await self.session.flush()
        return model.to_response()

    async def list_by_engagement(
        self, engagement_id: str, since_seq: int = 0
    ) -> list[AuditEventResponse]:
        stmt = (
            select(AuditEventModel)
            .where(AuditEventModel.engagement_id == engagement_id)
            .where(AuditEventModel.seq > since_seq)
            .order_by(AuditEventModel.seq.asc())
        )
        res = await self.session.execute(stmt)
        return [row.to_response() for row in res.scalars()]

    async def verify_integrity(self, engagement_id: str) -> tuple[bool, str]:
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

    # Immutability Guardrails
    async def delete(self, *args: Any, **kwargs: Any) -> bool:
        raise ImmutableAuditViolationError(
            "Audit records are cryptographically immutable. Deletion is forbidden."
        )

    async def update(self, *args: Any, **kwargs: Any) -> None:
        raise ImmutableAuditViolationError(
            "Audit records are cryptographically immutable. Updates are forbidden."
        )
