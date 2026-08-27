"""Human-in-the-Loop (HITL) approval gate domain models and repository."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.engagement import Base


class ApprovalStatus(StrEnum):
    """Lifecycle status of a human approval gate."""

    PENDING = "PENDING"
    GRANTED = "GRANTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ApprovalRequestSchema(BaseModel):
    """Payload to request operator authorization for a gated action."""

    id: str = Field(default_factory=lambda: f"gate-{uuid.uuid4().hex[:8]}")
    engagement_id: str
    task_id: str
    agent_id: str
    category: str = Field(..., description="Approval category (e.g. ACTIVE_EXPLOITATION_PROBE)")
    target_uri: str
    risk_description: str
    proposed_command: str = Field(default="")
    timeout_sec: int = Field(default=300)


class ApprovalDecisionRequest(BaseModel):
    """Payload submitted by operator to grant or reject a gate."""

    decision: ApprovalStatus = Field(..., description="GRANTED | REJECTED")
    operator_id: str
    decision_reason: str = Field(default="")


class ApprovalResponse(BaseModel):
    """Outbound API response representing an approval gate entity."""

    id: str
    engagement_id: str
    task_id: str
    agent_id: str
    category: str
    target_uri: str
    risk_description: str
    proposed_command: str
    status: ApprovalStatus
    operator_id: str | None
    decision_reason: str | None
    requested_at: str
    decided_at: str | None


class ApprovalModel(Base):
    """SQLAlchemy relational table mapping for Human Approval Gates."""

    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    engagement_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("engagements.id"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_employees.id"), nullable=False, index=True
    )

    category: Mapped[str] = mapped_column(String(64), nullable=False)
    target_uri: Mapped[str] = mapped_column(String(256), nullable=False)
    risk_description: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_command: Mapped[str] = mapped_column(Text, nullable=False, default="")

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ApprovalStatus.PENDING.value, index=True
    )
    operator_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    requested_at: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_at: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def to_response(self) -> ApprovalResponse:
        return ApprovalResponse(
            id=str(self.id),
            engagement_id=str(self.engagement_id),
            task_id=str(self.task_id),
            agent_id=str(self.agent_id),
            category=str(self.category),
            target_uri=str(self.target_uri),
            risk_description=str(self.risk_description),
            proposed_command=str(self.proposed_command),
            status=ApprovalStatus(str(self.status)),
            operator_id=str(self.operator_id) if self.operator_id else None,
            decision_reason=str(self.decision_reason) if self.decision_reason else None,
            requested_at=str(self.requested_at),
            decided_at=str(self.decided_at) if self.decided_at else None,
        )


class ApprovalRepository:
    """Repository handling Human-in-the-Loop (HITL) gate transactions."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    async def create_request(self, req: ApprovalRequestSchema) -> ApprovalResponse:
        """Create a new pending approval gate."""
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

        async with self.session_factory() as session:
            async with session.begin():
                session.add(model)
            await session.commit()
            return model.to_response()

    async def decide_gate(
        self, gate_id: str, decision: ApprovalDecisionRequest
    ) -> ApprovalResponse | None:
        """Record operator decision (GRANTED or REJECTED) on a pending gate."""
        now = datetime.now(UTC).isoformat()
        async with self.session_factory() as session:
            async with session.begin():
                model = await session.get(ApprovalModel, gate_id)
                if not model:
                    return None
                model.status = decision.decision.value
                model.operator_id = decision.operator_id
                model.decision_reason = decision.decision_reason
                model.decided_at = now
            await session.commit()
            return model.to_response()

    async def get_by_id(self, gate_id: str) -> ApprovalResponse | None:
        async with self.session_factory() as session:
            model = await session.get(ApprovalModel, gate_id)
            if model:
                return model.to_response()
            return None

    async def list_pending(self, engagement_id: str | None = None) -> list[ApprovalResponse]:
        """List all gates currently in PENDING state awaiting human input."""
        async with self.session_factory() as session:
            from sqlalchemy import select

            stmt = select(ApprovalModel).where(ApprovalModel.status == ApprovalStatus.PENDING.value)
            if engagement_id:
                stmt = stmt.where(ApprovalModel.engagement_id == engagement_id)
            stmt = stmt.order_by(ApprovalModel.requested_at.asc())
            res = await session.execute(stmt)
            return [row.to_response() for row in res.scalars()]
