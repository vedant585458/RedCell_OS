"""Concrete Approval repository wrapping SQLAlchemy session."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.approval import (
    ApprovalDecisionRequest,
    ApprovalModel,
    ApprovalRequestSchema,
    ApprovalResponse,
    ApprovalStatus,
)
from app.repositories.base import BaseRepository


class ApprovalRepository(BaseRepository[ApprovalModel, str]):
    """Typed repository for Human-in-the-Loop Approval Gate entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ApprovalModel, session)

    async def create_request(self, req: ApprovalRequestSchema) -> ApprovalResponse:
        now = datetime.now(UTC).isoformat()
        model = ApprovalModel(
            id=req.id,
            engagement_id=req.engagement_id,
            task_id=req.task_id,
            agent_id=req.agent_id,
            category=req.category,
            target_uri=req.target_uri,
            risk_description=req.risk_description,
            proposed_command=req.proposed_command,
            status=ApprovalStatus.PENDING.value,
            requested_at=now,
        )
        self.session.add(model)
        await self.session.flush()
        return model.to_response()

    async def decide_gate(
        self, gate_id: str, decision: ApprovalDecisionRequest
    ) -> ApprovalResponse | None:
        now = datetime.now(UTC).isoformat()
        model = await self.get_by_id(gate_id)
        if not model:
            return None
        model.status = decision.decision.value
        model.operator_id = decision.operator_id
        model.decision_reason = decision.decision_reason
        model.decided_at = now
        await self.session.flush()
        return model.to_response()

    async def list_pending(self, engagement_id: str | None = None) -> list[ApprovalResponse]:
        stmt = select(ApprovalModel).where(ApprovalModel.status == ApprovalStatus.PENDING.value)
        if engagement_id:
            stmt = stmt.where(ApprovalModel.engagement_id == engagement_id)
        stmt = stmt.order_by(ApprovalModel.requested_at.asc())
        res = await self.session.execute(stmt)
        return [row.to_response() for row in res.scalars()]
