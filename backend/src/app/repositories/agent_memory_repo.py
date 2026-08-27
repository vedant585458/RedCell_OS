"""Concrete AgentMemory repository wrapping SQLAlchemy session."""

import json
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.agent_memory import (
    AgentMemoryCreateRequest,
    AgentMemoryModel,
    AgentMemoryResponse,
    MemoryStatus,
    MemoryType,
)
from app.repositories.base import BaseRepository


class AgentMemoryRepository(BaseRepository[AgentMemoryModel, str]):
    """Typed repository handling CRUD and query transactions for persistent Agent Memories."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(AgentMemoryModel, session)

    async def create(self, req: AgentMemoryCreateRequest) -> AgentMemoryResponse:
        """Persist a new agent memory entry."""
        now = datetime.now(UTC).isoformat()
        model = AgentMemoryModel(
            id=req.id,
            role_id=req.role_id,
            target_domain_or_org=req.target_domain_or_org,
            engagement_id=req.engagement_id,
            memory_type=req.memory_type.value,
            key=req.key,
            content=req.content,
            confidence_score=req.confidence_score,
            source_task_id=req.source_task_id,
            source_agent_id=req.source_agent_id,
            status=req.status.value,
            approval_notes=req.approval_notes,
            metadata_json=json.dumps(req.metadata),
            created_at=now,
            updated_at=now,
        )
        self.session.add(model)
        await self.session.flush()
        return model.to_response()

    async def get_memory_response(self, memory_id: str) -> AgentMemoryResponse | None:
        """Fetch memory entry by unique ID."""
        model = await self.get_by_id(memory_id)
        if model:
            return model.to_response()
        return None

    async def update_status(
        self,
        memory_id: str,
        status: MemoryStatus | str,
        approval_notes: str = "",
    ) -> AgentMemoryResponse | None:
        """Update memory review status (e.g. PROPOSED -> APPROVED)."""
        status_val = status.value if isinstance(status, MemoryStatus) else status
        now = datetime.now(UTC).isoformat()

        model = await self.get_by_id(memory_id)
        if not model:
            return None
        model.status = status_val
        if approval_notes:
            model.approval_notes = approval_notes
        model.updated_at = now
        await self.session.flush()
        return model.to_response()

    async def query_memories(
        self,
        role_id: str | None = None,
        target: str | None = None,
        engagement_id: str | None = None,
        memory_type: MemoryType | str | None = None,
        status: MemoryStatus | str | None = MemoryStatus.APPROVED,
    ) -> list[AgentMemoryResponse]:
        """Query persistent long-term memories matching role, target, and status."""
        from urllib.parse import urlparse

        stmt = select(AgentMemoryModel)

        if role_id:
            stmt = stmt.where(AgentMemoryModel.role_id == role_id)

        if target:
            parsed = urlparse(target if "://" in target else f"//{target}")
            host_clean = (parsed.hostname or target).strip().lower()
            target_clean = target.strip().lower()

            target_conditions = [
                AgentMemoryModel.target_domain_or_org.ilike(f"%{host_clean}%"),
                AgentMemoryModel.target_domain_or_org.ilike(f"%{target_clean}%"),
                AgentMemoryModel.target_domain_or_org == "*",
            ]
            for part in host_clean.split("."):
                if len(part) >= 3 and part not in ("com", "org", "net", "local", "internal"):
                    target_conditions.append(
                        AgentMemoryModel.target_domain_or_org.ilike(f"%{part}%")
                    )

            stmt = stmt.where(or_(*target_conditions))

        if engagement_id:
            stmt = stmt.where(
                or_(
                    AgentMemoryModel.engagement_id == engagement_id,
                    AgentMemoryModel.engagement_id.is_(None),
                )
            )

        if memory_type:
            m_type = memory_type.value if isinstance(memory_type, MemoryType) else str(memory_type)
            stmt = stmt.where(AgentMemoryModel.memory_type == m_type)

        if status:
            s_val = status.value if isinstance(status, MemoryStatus) else str(status)
            stmt = stmt.where(AgentMemoryModel.status == s_val)

        stmt = stmt.order_by(
            AgentMemoryModel.confidence_score.desc(),
            AgentMemoryModel.created_at.desc(),
        )

        res = await self.session.execute(stmt)
        return [row.to_response() for row in res.scalars().all()]
