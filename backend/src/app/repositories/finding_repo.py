"""Concrete Finding, Evidence, and RiskScore repository wrapping SQLAlchemy session."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.finding import (
    EvidenceCreateRequest,
    EvidenceModel,
    EvidenceResponse,
    FindingCreateRequest,
    FindingModel,
    FindingResponse,
    FindingStatus,
    RiskScoreModel,
)
from app.repositories.base import BaseRepository


class FindingRepository(BaseRepository[FindingModel, str]):
    """Typed repository for Finding, Evidence, and RiskScore operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(FindingModel, session)

    async def create_finding(self, req: FindingCreateRequest) -> FindingResponse:
        now = datetime.now(UTC).isoformat()
        finding_model = FindingModel(
            id=req.finding_id,
            engagement_id=req.engagement_id,
            task_id=req.task_id,
            agent_id=req.agent_id,
            title=req.title,
            description=req.description,
            severity=req.severity.value,
            status=req.status.value,
            cwe_id=req.cwe_id,
            cve_id=req.cve_id,
            target_endpoint=req.target_endpoint,
            remediation_guidance=req.remediation_guidance,
            created_at=now,
            updated_at=now,
        )
        self.session.add(finding_model)

        for ev in req.evidence:
            ev_model = EvidenceModel(
                id=ev.id,
                finding_id=req.finding_id,
                evidence_type=ev.evidence_type.value,
                artifact_path=ev.artifact_path,
                sha256_hash=ev.sha256_hash,
                description=ev.description,
                created_at=now,
            )
            self.session.add(ev_model)

        if req.risk_score:
            risk_model = RiskScoreModel(
                id=f"risk-{uuid.uuid4().hex[:8]}",
                finding_id=req.finding_id,
                cvss_v31_base_score=req.risk_score.cvss_v31_base_score,
                cvss_vector=req.risk_score.cvss_vector,
                attack_vector=req.risk_score.attack_vector,
                attack_complexity=req.risk_score.attack_complexity,
                privileges_required=req.risk_score.privileges_required,
                user_interaction=req.risk_score.user_interaction,
                scope=req.risk_score.scope,
                confidentiality_impact=req.risk_score.confidentiality_impact,
                integrity_impact=req.risk_score.integrity_impact,
                availability_impact=req.risk_score.availability_impact,
                created_at=now,
            )
            self.session.add(risk_model)

        await self.session.flush()
        return await self.get_finding_response(req.finding_id)  # type: ignore[return-value]

    async def get_finding_response(self, finding_id: str) -> FindingResponse | None:
        finding_model = await self.get_by_id(finding_id)
        if not finding_model:
            return None

        # Fetch evidence records
        ev_stmt = (
            select(EvidenceModel)
            .where(EvidenceModel.finding_id == finding_id)
            .order_by(EvidenceModel.created_at.asc())
        )
        ev_res = await self.session.execute(ev_stmt)
        evidence_list = [row.to_response() for row in ev_res.scalars()]

        # Fetch risk score
        risk_stmt = select(RiskScoreModel).where(RiskScoreModel.finding_id == finding_id)
        risk_res = await self.session.execute(risk_stmt)
        risk_row = risk_res.scalar_one_or_none()
        risk_score = risk_row.to_response() if risk_row else None

        return finding_model.to_response(evidence_list=evidence_list, risk_score=risk_score)

    async def add_evidence(self, finding_id: str, req: EvidenceCreateRequest) -> EvidenceResponse:
        now = datetime.now(UTC).isoformat()
        ev_model = EvidenceModel(
            id=req.id,
            finding_id=finding_id,
            evidence_type=req.evidence_type.value,
            artifact_path=req.artifact_path,
            sha256_hash=req.sha256_hash,
            description=req.description,
            created_at=now,
        )
        self.session.add(ev_model)
        await self.session.flush()
        return ev_model.to_response()

    async def list_by_engagement(
        self, engagement_id: str, status: FindingStatus | str | None = None
    ) -> list[FindingResponse]:
        stmt = select(FindingModel).where(FindingModel.engagement_id == engagement_id)
        if status:
            status_val = status.value if isinstance(status, FindingStatus) else status
            stmt = stmt.where(FindingModel.status == status_val)
        stmt = stmt.order_by(FindingModel.created_at.asc())

        res = await self.session.execute(stmt)
        finding_models = res.scalars().all()

        results: list[FindingResponse] = []
        for f in finding_models:
            ev_stmt = (
                select(EvidenceModel)
                .where(EvidenceModel.finding_id == f.id)
                .order_by(EvidenceModel.created_at.asc())
            )
            ev_res = await self.session.execute(ev_stmt)
            evidence_list = [row.to_response() for row in ev_res.scalars()]

            risk_stmt = select(RiskScoreModel).where(RiskScoreModel.finding_id == f.id)
            risk_res = await self.session.execute(risk_stmt)
            risk_row = risk_res.scalar_one_or_none()
            risk_score = risk_row.to_response() if risk_row else None

            results.append(f.to_response(evidence_list=evidence_list, risk_score=risk_score))

        return results
