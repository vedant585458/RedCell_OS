"""Unit tests for Finding, Evidence, and RiskScore domain models and repository."""

import pytest
from app.domain.agent import AgentCreateRequest, AgentStatus, AIEmployeeRepository
from app.domain.department import DepartmentCreateRequest, DepartmentRepository
from app.domain.engagement import (
    Base,
    EngagementCreateRequest,
    EngagementRepository,
)
from app.domain.finding import (
    EvidenceCreateRequest,
    EvidenceType,
    FindingCreateRequest,
    FindingRepository,
    FindingSeverity,
    FindingStatus,
    RiskScoreCreateRequest,
)
from app.domain.role import RoleCreateRequest, RoleRepository
from app.domain.task import TaskCreateRequest, TaskRepository
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_finding_with_linked_evidence_and_risk_score():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    dept_repo = DepartmentRepository(session_factory=session_factory)
    role_repo = RoleRepository(session_factory=session_factory)
    eng_repo = EngagementRepository(session_factory=session_factory)
    agent_repo = AIEmployeeRepository(session_factory=session_factory)
    task_repo = TaskRepository(session_factory=session_factory)
    finding_repo = FindingRepository(session_factory=session_factory)

    # 1. Seed Parent Data
    await dept_repo.upsert(
        DepartmentCreateRequest(id="dept_vulnerability", name="Vuln Dept")
    )
    await role_repo.upsert(
        RoleCreateRequest(
            id="role_web_vuln_assessor",
            name="Web Assessor",
            department_id="dept_vulnerability",
            system_prompt_template="prompts/roles/web_vuln_assessor.jinja2",
        )
    )
    await eng_repo.create(
        EngagementCreateRequest(
            engagement_id="eng-mvp-001",
            title="MVP Test Engagement",
            organization="Acme Labs",
            authorized_by="Lead Security Architect",
        )
    )
    await agent_repo.create(
        AgentCreateRequest(
            id="agent-vuln-01",
            role_id="role_web_vuln_assessor",
            department_id="dept_vulnerability",
            display_name="Vuln Assessor Agent 1",
            status=AgentStatus.EXECUTING,
        )
    )
    await task_repo.create_task(
        TaskCreateRequest(
            task_id="TASK_02_VULN_SCAN",
            engagement_id="eng-mvp-001",
            department_id="dept_vulnerability",
            title="Scan Config Endpoint",
            assigned_role="role_web_vuln_assessor",
            assigned_agent_id="agent-vuln-01",
        )
    )

    # 2. Create Finding with Linked Evidence Artifact and CVSS Risk Score
    finding_req = FindingCreateRequest(
        finding_id="FINDING-001",
        engagement_id="eng-mvp-001",
        task_id="TASK_02_VULN_SCAN",
        agent_id="agent-vuln-01",
        title="Unauthenticated Sensitive Configuration Exposure",
        description="Debug endpoint /api/v1/debug/config discloses JWT secrets and database credentials without authentication.",
        severity=FindingSeverity.HIGH,
        status=FindingStatus.DRAFT,
        cwe_id="CWE-200",
        cve_id=None,
        target_endpoint="http://127.0.0.1:8088/api/v1/debug/config",
        remediation_guidance="Enforce authentication on all debug endpoints and remove sensitive credentials from configuration files.",
        evidence=[
            EvidenceCreateRequest(
                id="ev-001",
                evidence_type=EvidenceType.HTTP_REQUEST_RESPONSE,
                artifact_path="/data/engagements/eng-mvp-001/evidence/sha256_e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855.raw",
                sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                description="HTTP GET /api/v1/debug/config response dump revealing raw JWT signing key.",
            )
        ],
        risk_score=RiskScoreCreateRequest(
            cvss_v31_base_score=7.5,
            cvss_vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
            attack_vector="NETWORK",
            attack_complexity="LOW",
            privileges_required="NONE",
            user_interaction="NONE",
            scope="UNCHANGED",
            confidentiality_impact="HIGH",
            integrity_impact="NONE",
            availability_impact="NONE",
        ),
    )

    created = await finding_repo.create(finding_req)
    assert created.finding_id == "FINDING-001"
    assert created.severity == FindingSeverity.HIGH
    assert created.status == FindingStatus.DRAFT
    assert created.cwe_id == "CWE-200"
    assert len(created.evidence) == 1
    assert created.evidence[0].evidence_type == EvidenceType.HTTP_REQUEST_RESPONSE
    assert (
        created.evidence[0].sha256_hash
        == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert created.risk_score is not None
    assert created.risk_score.cvss_v31_base_score == 7.5

    # 3. Add Secondary Evidence Artifact
    ev2 = await finding_repo.add_evidence(
        finding_id="FINDING-001",
        req=EvidenceCreateRequest(
            id="ev-002",
            evidence_type=EvidenceType.RAW_OUTPUT,
            artifact_path="/data/engagements/eng-mvp-001/evidence/sha256_8f434346648f3223e1b0c44298fc1c149afbf4c8996fb92427ae41e4649b934c.raw",
            sha256_hash="8f434346648f3223e1b0c44298fc1c149afbf4c8996fb92427ae41e4649b934c",
            description="Nuclei scan finding output JSON.",
        ),
    )
    assert ev2.id == "ev-002"

    # 4. Read back and verify 2 evidence records
    fetched = await finding_repo.get_by_id("FINDING-001")
    assert fetched is not None
    assert len(fetched.evidence) == 2

    # 5. Transition Status: DRAFT -> VALIDATED -> REPORTED
    validated = await finding_repo.update_status("FINDING-001", FindingStatus.VALIDATED)
    assert validated is not None
    assert validated.status == FindingStatus.VALIDATED

    reported = await finding_repo.update_status("FINDING-001", FindingStatus.REPORTED)
    assert reported is not None
    assert reported.status == FindingStatus.REPORTED

    # 6. List findings in engagement
    eng_findings = await finding_repo.list_by_engagement("eng-mvp-001")
    assert len(eng_findings) == 1
    assert eng_findings[0].finding_id == "FINDING-001"
    assert eng_findings[0].status == FindingStatus.REPORTED

    await engine.dispose()
