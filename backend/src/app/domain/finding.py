"""Finding, Evidence, and RiskScore domain models, Pydantic schemas, and SQLAlchemy ORM entities."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.engagement import Base


class FindingStatus(StrEnum):
    """Lifecycle status enum for security findings."""

    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    REPORTED = "REPORTED"


class FindingSeverity(StrEnum):
    """Categorical severity rating based on CVSS scoring."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFORMATIONAL = "INFORMATIONAL"


class EvidenceType(StrEnum):
    """Types of evidence artifacts linked to a finding."""

    RAW_OUTPUT = "RAW_OUTPUT"
    HTTP_REQUEST_RESPONSE = "HTTP_REQUEST_RESPONSE"
    SCREENSHOT = "SCREENSHOT"
    LOG_SNIPPET = "LOG_SNIPPET"
    PCAP_CAPTURE = "PCAP_CAPTURE"
    CODE_SNIPPET = "CODE_SNIPPET"


# ==============================================================================
# Pydantic Schemas for API Validation & I/O
# ==============================================================================


class EvidenceCreateRequest(BaseModel):
    """Payload to attach an evidence artifact reference to a finding."""

    id: str = Field(default_factory=lambda: f"ev-{uuid.uuid4().hex[:8]}")
    evidence_type: EvidenceType = Field(default=EvidenceType.RAW_OUTPUT)
    artifact_path: str = Field(
        ..., description="Filesystem path reference to raw artifact in CAS (ADR-004)"
    )
    sha256_hash: str = Field(
        ..., min_length=64, max_length=64, description="Cryptographic SHA-256 hash of artifact"
    )
    description: str = Field(default="")


class EvidenceResponse(BaseModel):
    """Outbound API response representing an evidence artifact."""

    id: str
    finding_id: str
    evidence_type: EvidenceType
    artifact_path: str
    sha256_hash: str
    description: str
    created_at: str


class RiskScoreCreateRequest(BaseModel):
    """Payload to record CVSS v3.1 risk metrics for a finding."""

    cvss_v31_base_score: float = Field(
        ..., ge=0.0, le=10.0, description="CVSS v3.1 base score (0.0 - 10.0)"
    )
    cvss_vector: str = Field(
        default="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
        description="Standard CVSS v3.1 vector string",
    )
    attack_vector: str = Field(default="NETWORK")
    attack_complexity: str = Field(default="LOW")
    privileges_required: str = Field(default="NONE")
    user_interaction: str = Field(default="NONE")
    scope: str = Field(default="UNCHANGED")
    confidentiality_impact: str = Field(default="HIGH")
    integrity_impact: str = Field(default="NONE")
    availability_impact: str = Field(default="NONE")


class RiskScoreResponse(BaseModel):
    """Outbound API response representing risk score metrics."""

    id: str
    finding_id: str
    cvss_v31_base_score: float
    cvss_vector: str
    attack_vector: str
    attack_complexity: str
    privileges_required: str
    user_interaction: str
    scope: str
    confidentiality_impact: str
    integrity_impact: str
    availability_impact: str
    created_at: str


class FindingCreateRequest(BaseModel):
    """Payload to record a newly discovered vulnerability finding."""

    finding_id: str = Field(default_factory=lambda: f"FINDING-{uuid.uuid4().hex[:6].upper()}")
    engagement_id: str = Field(..., description="Parent engagement identifier")
    task_id: str = Field(..., description="Task in which finding was discovered")
    agent_id: str = Field(..., description="Discovering agent identifier")
    title: str = Field(..., min_length=3, max_length=128)
    description: str = Field(..., min_length=5)
    severity: FindingSeverity = Field(default=FindingSeverity.HIGH)
    status: FindingStatus = Field(default=FindingStatus.DRAFT)
    cwe_id: str = Field(default="CWE-200", description="Common Weakness Enumeration ID")
    cve_id: str | None = Field(default=None, description="Optional CVE ID reference")
    target_endpoint: str = Field(..., description="Vulnerable URI or host:port endpoint")
    remediation_guidance: str = Field(default="")
    evidence: list[EvidenceCreateRequest] = Field(default_factory=list)
    risk_score: RiskScoreCreateRequest | None = None


class FindingResponse(BaseModel):
    """Outbound API response representing a complete Finding with linked Evidence and RiskScore."""

    finding_id: str
    engagement_id: str
    task_id: str
    agent_id: str
    title: str
    description: str
    severity: FindingSeverity
    status: FindingStatus
    cwe_id: str
    cve_id: str | None
    target_endpoint: str
    remediation_guidance: str
    evidence: list[EvidenceResponse]
    risk_score: RiskScoreResponse | None
    created_at: str
    updated_at: str


# ==============================================================================
# SQLAlchemy 2.0 ORM Entity Definitions
# ==============================================================================


class FindingModel(Base):
    """SQLAlchemy relational table mapping for Security Findings."""

    __tablename__ = "findings"

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

    title: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    severity: Mapped[str] = mapped_column(
        String(32), nullable=False, default=FindingSeverity.HIGH.value, index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=FindingStatus.DRAFT.value, index=True
    )
    cwe_id: Mapped[str] = mapped_column(String(64), nullable=False, default="CWE-200")
    cve_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_endpoint: Mapped[str] = mapped_column(String(256), nullable=False)
    remediation_guidance: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)

    def to_response(
        self,
        evidence_list: list[EvidenceResponse] | None = None,
        risk_score: RiskScoreResponse | None = None,
    ) -> FindingResponse:
        """Convert ORM model to validated Pydantic FindingResponse."""
        return FindingResponse(
            finding_id=str(self.id),
            engagement_id=str(self.engagement_id),
            task_id=str(self.task_id),
            agent_id=str(self.agent_id),
            title=str(self.title),
            description=str(self.description),
            severity=FindingSeverity(str(self.severity)),
            status=FindingStatus(str(self.status)),
            cwe_id=str(self.cwe_id),
            cve_id=str(self.cve_id) if self.cve_id else None,
            target_endpoint=str(self.target_endpoint),
            remediation_guidance=str(self.remediation_guidance),
            evidence=evidence_list or [],
            risk_score=risk_score,
            created_at=str(self.created_at),
            updated_at=str(self.updated_at),
        )


class EvidenceModel(Base):
    """SQLAlchemy relational table mapping for Evidence Artifacts (filesystem references)."""

    __tablename__ = "evidence_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    finding_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("findings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evidence_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EvidenceType.RAW_OUTPUT.value
    )
    artifact_path: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)

    def to_response(self) -> EvidenceResponse:
        return EvidenceResponse(
            id=str(self.id),
            finding_id=str(self.finding_id),
            evidence_type=EvidenceType(str(self.evidence_type)),
            artifact_path=str(self.artifact_path),
            sha256_hash=str(self.sha256_hash),
            description=str(self.description),
            created_at=str(self.created_at),
        )


class RiskScoreModel(Base):
    """SQLAlchemy relational table mapping for CVSS Risk Metrics."""

    __tablename__ = "risk_scores"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    finding_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("findings.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    cvss_v31_base_score: Mapped[float] = mapped_column(Float, nullable=False)
    cvss_vector: Mapped[str] = mapped_column(String(128), nullable=False)
    attack_vector: Mapped[str] = mapped_column(String(32), nullable=False, default="NETWORK")
    attack_complexity: Mapped[str] = mapped_column(String(32), nullable=False, default="LOW")
    privileges_required: Mapped[str] = mapped_column(String(32), nullable=False, default="NONE")
    user_interaction: Mapped[str] = mapped_column(String(32), nullable=False, default="NONE")
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="UNCHANGED")
    confidentiality_impact: Mapped[str] = mapped_column(String(32), nullable=False, default="HIGH")
    integrity_impact: Mapped[str] = mapped_column(String(32), nullable=False, default="NONE")
    availability_impact: Mapped[str] = mapped_column(String(32), nullable=False, default="NONE")
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)

    def to_response(self) -> RiskScoreResponse:
        return RiskScoreResponse(
            id=str(self.id),
            finding_id=str(self.finding_id),
            cvss_v31_base_score=float(self.cvss_v31_base_score),
            cvss_vector=str(self.cvss_vector),
            attack_vector=str(self.attack_vector),
            attack_complexity=str(self.attack_complexity),
            privileges_required=str(self.privileges_required),
            user_interaction=str(self.user_interaction),
            scope=str(self.scope),
            confidentiality_impact=str(self.confidentiality_impact),
            integrity_impact=str(self.integrity_impact),
            availability_impact=str(self.availability_impact),
            created_at=str(self.created_at),
        )


# ==============================================================================
# Repository Layer for Findings, Evidence, and Risk Scores
# ==============================================================================


class FindingRepository:
    """Repository managing Finding CRUD, linked Evidence artifacts, and CVSS Risk Scores."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    async def create(
        self,
        req: FindingCreateRequest,
    ) -> FindingResponse:
        """Create and persist a new Finding with optional initial evidence and risk score."""
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

        async with self.session_factory() as session:
            async with session.begin():
                session.add(finding_model)

                # Persist initial evidence list if provided
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
                    session.add(ev_model)

                # Persist risk score if provided
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
                    session.add(risk_model)

            await session.commit()

        return await self.get_by_id(req.finding_id)  # type: ignore[return-value]

    async def get_by_id(self, finding_id: str) -> FindingResponse | None:
        """Fetch a finding by ID along with its linked evidence records and risk score."""
        async with self.session_factory() as session:
            from sqlalchemy import select

            finding_model = await session.get(FindingModel, finding_id)
            if not finding_model:
                return None

            # Fetch linked evidence records
            ev_stmt = (
                select(EvidenceModel)
                .where(EvidenceModel.finding_id == finding_id)
                .order_by(EvidenceModel.created_at.asc())
            )
            ev_res = await session.execute(ev_stmt)
            evidence_list = [row.to_response() for row in ev_res.scalars()]

            # Fetch risk score
            risk_stmt = select(RiskScoreModel).where(RiskScoreModel.finding_id == finding_id)
            risk_res = await session.execute(risk_stmt)
            risk_row = risk_res.scalar_one_or_none()
            risk_score = risk_row.to_response() if risk_row else None

            return finding_model.to_response(evidence_list=evidence_list, risk_score=risk_score)

    async def add_evidence(self, finding_id: str, req: EvidenceCreateRequest) -> EvidenceResponse:
        """Attach a new evidence artifact reference to an existing finding."""
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

        async with self.session_factory() as session:
            async with session.begin():
                session.add(ev_model)
            await session.commit()
            return ev_model.to_response()

    async def set_risk_score(
        self, finding_id: str, req: RiskScoreCreateRequest
    ) -> RiskScoreResponse:
        """Set or update CVSS risk score metrics for a finding."""
        now = datetime.now(UTC).isoformat()
        async with self.session_factory() as session:
            async with session.begin():
                from sqlalchemy import select

                stmt = select(RiskScoreModel).where(RiskScoreModel.finding_id == finding_id)
                res = await session.execute(stmt)
                model = res.scalar_one_or_none()

                if model:
                    model.cvss_v31_base_score = req.cvss_v31_base_score
                    model.cvss_vector = req.cvss_vector
                    model.attack_vector = req.attack_vector
                    model.attack_complexity = req.attack_complexity
                    model.privileges_required = req.privileges_required
                    model.user_interaction = req.user_interaction
                    model.scope = req.scope
                    model.confidentiality_impact = req.confidentiality_impact
                    model.integrity_impact = req.integrity_impact
                    model.availability_impact = req.availability_impact
                else:
                    model = RiskScoreModel(
                        id=f"risk-{uuid.uuid4().hex[:8]}",
                        finding_id=finding_id,
                        cvss_v31_base_score=req.cvss_v31_base_score,
                        cvss_vector=req.cvss_vector,
                        attack_vector=req.attack_vector,
                        attack_complexity=req.attack_complexity,
                        privileges_required=req.privileges_required,
                        user_interaction=req.user_interaction,
                        scope=req.scope,
                        confidentiality_impact=req.confidentiality_impact,
                        integrity_impact=req.integrity_impact,
                        availability_impact=req.availability_impact,
                        created_at=now,
                    )
                    session.add(model)

            await session.commit()
            return model.to_response()

    async def update_status(
        self, finding_id: str, status: FindingStatus | str
    ) -> FindingResponse | None:
        """Update finding validation lifecycle status (DRAFT -> VALIDATED -> REPORTED)."""
        status_val = status.value if isinstance(status, FindingStatus) else status
        async with self.session_factory() as session:
            async with session.begin():
                model = await session.get(FindingModel, finding_id)
                if not model:
                    return None
                model.status = status_val
                model.updated_at = datetime.now(UTC).isoformat()
            await session.commit()

        return await self.get_by_id(finding_id)

    async def list_by_engagement(
        self,
        engagement_id: str,
        status: FindingStatus | str | None = None,
    ) -> list[FindingResponse]:
        """List all findings within an engagement, optionally filtered by lifecycle status."""
        async with self.session_factory() as session:
            from sqlalchemy import select

            stmt = select(FindingModel).where(FindingModel.engagement_id == engagement_id)
            if status:
                status_val = status.value if isinstance(status, FindingStatus) else status
                stmt = stmt.where(FindingModel.status == status_val)
            stmt = stmt.order_by(FindingModel.created_at.asc())

            res = await session.execute(stmt)
            finding_models = res.scalars().all()

            results: list[FindingResponse] = []
            for f in finding_models:
                # Fetch linked evidence
                ev_stmt = (
                    select(EvidenceModel)
                    .where(EvidenceModel.finding_id == f.id)
                    .order_by(EvidenceModel.created_at.asc())
                )
                ev_res = await session.execute(ev_stmt)
                evidence_list = [row.to_response() for row in ev_res.scalars()]

                # Fetch risk score
                risk_stmt = select(RiskScoreModel).where(RiskScoreModel.finding_id == f.id)
                risk_res = await session.execute(risk_stmt)
                risk_row = risk_res.scalar_one_or_none()
                risk_score = risk_row.to_response() if risk_row else None

                results.append(f.to_response(evidence_list=evidence_list, risk_score=risk_score))

            return results
