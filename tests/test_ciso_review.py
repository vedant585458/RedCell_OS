"""Unit and integration tests for CISO finding review and report approval workflow."""

import pytest
from app.ciso.review import CisoFindingReviewService, FindingQualityReport
from app.domain.engagement import Base, EngagementCreateRequest
from app.domain.finding import (
    EvidenceCreateRequest,
    EvidenceType,
    FindingCreateRequest,
    FindingSeverity,
    FindingStatus,
    RiskScoreCreateRequest,
)
from app.domain.task import TaskCreateRequest
from app.llm.mock_brain import MockAgentBrain
from app.repositories.unit_of_work import UnitOfWork
from app.services.org_bootstrap import OrgBootstrapService
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_environment():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Bootstrap default departments, roles, and baseline agents (including agent-vuln-01)
    bootstrap = OrgBootstrapService(session_factory)
    await bootstrap.bootstrap_organization()

    async with UnitOfWork(session_factory) as uow:
        await uow.engagements.create_engagement(
            EngagementCreateRequest(
                engagement_id="eng-rev-001",
                title="Review Test Engagement",
                organization="Acme",
                authorized_by="Lead CISO",
            )
        )
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK-01",
                engagement_id="eng-rev-001",
                department_id="dept_vulnerability",
                title="Scan Target",
                assigned_role="role_web_vuln_assessor",
                assigned_agent_id="agent-vuln-01",
            )
        )
        await uow.commit()

    return session_factory, engine


@pytest.mark.asyncio
async def test_ciso_review_approves_high_quality_finding():
    session_factory, engine = await setup_test_environment()
    try:
        # Create a valid finding in DB
        async with UnitOfWork(session_factory) as uow:
            await uow.findings.create_finding(
                FindingCreateRequest(
                    finding_id="FINDING-HIGH-01",
                    engagement_id="eng-rev-001",
                    task_id="TASK-01",
                    agent_id="agent-vuln-01",
                    title="Hardcoded API Secret in Debug Endpoint",
                    description="Unauthenticated debug endpoint discloses JWT private signing keys and database password.",
                    severity=FindingSeverity.HIGH,
                    status=FindingStatus.DRAFT,
                    cwe_id="CWE-200",
                    target_endpoint="http://127.0.0.1:8088/api/v1/debug/config",
                    remediation_guidance="Disable debug mode in production and remove hardcoded secrets.",
                    evidence=[
                        EvidenceCreateRequest(
                            id="ev-01",
                            evidence_type=EvidenceType.RAW_OUTPUT,
                            artifact_path="/data/evidence/debug.json",
                            sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                        )
                    ],
                    risk_score=RiskScoreCreateRequest(cvss_v31_base_score=7.5),
                )
            )
            await uow.commit()

        # Mock LLM Judge Decision
        approved_decision = FindingQualityReport(
            finding_id="FINDING-HIGH-01",
            decision="APPROVED",
            quality_score=9.2,
            evidence_sufficient=True,
            remediation_actionable=True,
            cvss_score_accurate=True,
            feedback_to_agent="Excellent evidence proof and clear remediation guidance.",
        )

        mock_brain = MockAgentBrain(
            scripted_responses={FindingQualityReport: approved_decision}
        )
        review_service = CisoFindingReviewService(
            session_factory=session_factory, brain=mock_brain
        )

        result = await review_service.review_finding("FINDING-HIGH-01")

        assert result.decision == "APPROVED"
        assert result.quality_score == 9.2

        # Verify DB updates: finding status must be REPORTED and Approval entity must be GRANTED
        async with UnitOfWork(session_factory) as uow:
            f = await uow.findings.get_finding_response("FINDING-HIGH-01")
            assert f is not None
            assert f.status == FindingStatus.REPORTED

            # Check approval record
            appr = await uow.approvals.get_by_id("gate-ciso-rev-FINDING-HIGH-01")
            assert appr is not None
            assert appr.status == "GRANTED"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ciso_review_rejects_low_quality_finding_and_routes_rework():
    session_factory, engine = await setup_test_environment()
    try:
        # Create an incomplete finding with missing evidence
        async with UnitOfWork(session_factory) as uow:
            await uow.findings.create_finding(
                FindingCreateRequest(
                    finding_id="FINDING-LOW-01",
                    engagement_id="eng-rev-001",
                    task_id="TASK-01",
                    agent_id="agent-vuln-01",
                    title="Possible SQL Injection",
                    description="Vague injection suspected without proof.",
                    severity=FindingSeverity.HIGH,
                    status=FindingStatus.VALIDATED,
                    cwe_id="CWE-89",
                    target_endpoint="http://127.0.0.1:8088/api/search",
                    remediation_guidance="Fix query.",
                    evidence=[],  # No evidence!
                )
            )
            await uow.commit()

        rejected_decision = FindingQualityReport(
            finding_id="FINDING-LOW-01",
            decision="REJECTED_NEEDS_REWORK",
            quality_score=3.5,
            evidence_sufficient=False,
            remediation_actionable=False,
            cvss_score_accurate=False,
            feedback_to_agent="Missing proof of concept HTTP request/response artifact.",
        )

        mock_brain = MockAgentBrain(
            scripted_responses={FindingQualityReport: rejected_decision}
        )
        review_service = CisoFindingReviewService(
            session_factory=session_factory, brain=mock_brain
        )

        result = await review_service.review_finding("FINDING-LOW-01")

        assert result.decision == "REJECTED_NEEDS_REWORK"

        # Verify DB updates: finding status reverted to DRAFT, message dispatched to discovering agent
        async with UnitOfWork(session_factory) as uow:
            f = await uow.findings.get_finding_response("FINDING-LOW-01")
            assert f is not None
            assert f.status == FindingStatus.DRAFT

            # Check rejection approval record
            appr = await uow.approvals.get_by_id("gate-ciso-rev-FINDING-LOW-01")
            assert appr is not None
            assert appr.status == "REJECTED"

            # Check feedback message in agent mailbox
            messages = await uow.messages.list_by_task("TASK-01")
            assert len(messages) >= 1
            rework_msg = next(
                m for m in messages if m.sender_agent_id == "agent-ciso-01"
            )
            assert "Missing proof of concept" in rework_msg.content
    finally:
        await engine.dispose()
