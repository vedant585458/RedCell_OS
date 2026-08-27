"""Unit and integration tests for ContextBuilder, working memory assembly, pinned Scope/ROE preservation, and token budget truncation."""

import pytest
from app.agents.context_builder import ContextBuilder, estimate_tokens
from app.domain.communication import MessageCreateRequest, MessageType
from app.domain.engagement import (
    Base,
    EngagementCreateRequest,
    RulesOfEngagementSchema,
    TargetScopeSchema,
)
from app.domain.finding import (
    EvidenceCreateRequest,
    FindingCreateRequest,
    FindingSeverity,
    RiskScoreCreateRequest,
)
from app.domain.task import TaskCreateRequest, TaskStatus
from app.repositories.unit_of_work import UnitOfWork
from app.services.org_bootstrap import OrgBootstrapService
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_environment():
    """Setup test SQLite database, seed org, engagement with explicit scope/ROE, parent/child tasks, findings, and messages."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    bootstrap = OrgBootstrapService(session_factory)
    await bootstrap.bootstrap_organization()

    async with UnitOfWork(session_factory) as uow:
        # 1. Create Engagement with strict Scope and ROE
        await uow.engagements.create_engagement(
            EngagementCreateRequest(
                engagement_id="eng-ctx-test",
                title="Target Assessment Engagement",
                organization="SecureBank Financial",
                authorized_by="CISO Office",
                target_scope=TargetScopeSchema(
                    allowed_ipv4_cidrs=["192.168.1.0/24", "10.0.5.0/24"],
                    allowed_domains=["*.securebank.local", "api.securebank.local"],
                    allowed_ports=["80", "443", "8443"],
                    excluded_ipv4_cidrs=["192.168.1.254/32"],
                    excluded_domains=["prod-payment.securebank.local"],
                ),
                rules_of_engagement=RulesOfEngagementSchema(
                    max_intensity="vulnerability_verification",
                    prohibited_actions=["DENIAL_OF_SERVICE", "PERMANENT_DESTRUCTION"],
                    max_packets_per_sec=1000,
                    max_bandwidth_kbps=8192,
                ),
            )
        )

        # 2. Create Parent Mission Task (Recon)
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_PARENT_MISSION",
                engagement_id="eng-ctx-test",
                department_id="dept_recon",
                title="Perimeter Intelligence Gathering",
                assigned_role="role_web_discovery",
                priority=3,
            )
        )

        # 3. Create Child Task (Web Endpoint Assessment)
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_CHILD_PROBE",
                engagement_id="eng-ctx-test",
                department_id="dept_vulnerability",
                title="API Vulnerability Scan",
                description="Probe JSON REST endpoints on https://api.securebank.local/v1/auth",
                assigned_role="role_web_vuln_assessor",
                assigned_agent_id="agent-vuln-01",
                parent_task_id="TASK_PARENT_MISSION",
                priority=4,
                input_context={
                    "target": "https://api.securebank.local/v1/auth",
                    "probe_depth": 3,
                },
            )
        )
        await uow.tasks.update_status("TASK_CHILD_PROBE", TaskStatus.RUNNING)

        # 4. Create Findings (1 Critical on target endpoint, 1 Low on unrelated endpoint)
        await uow.findings.create_finding(
            FindingCreateRequest(
                finding_id="FINDING-CRIT-01",
                engagement_id="eng-ctx-test",
                task_id="TASK_CHILD_PROBE",
                agent_id="agent-vuln-01",
                title="Unauthenticated SQL Injection in Auth Endpoint",
                description="Blind SQLi vulnerability confirmed via time delay payload on /v1/auth.",
                severity=FindingSeverity.CRITICAL,
                target_endpoint="https://api.securebank.local/v1/auth",
                evidence=[
                    EvidenceCreateRequest(
                        artifact_path="/data/evidence/sqli_poc.txt",
                        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    )
                ],
                risk_score=RiskScoreCreateRequest(
                    cvss_v31_base_score=9.8,
                    cvss_vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
                ),
            )
        )
        await uow.findings.create_finding(
            FindingCreateRequest(
                finding_id="FINDING-LOW-02",
                engagement_id="eng-ctx-test",
                task_id="TASK_PARENT_MISSION",
                agent_id="agent-recon-01",
                title="TLS 1.0 Supported on Legacy Subdomain",
                description="Deprecated TLS cipher suites active on legacy.securebank.local.",
                severity=FindingSeverity.LOW,
                target_endpoint="https://legacy.securebank.local",
            )
        )

        # 5. Create Messages (1 task-specific briefing, 1 general announcement)
        await uow.messages.send_message(
            MessageCreateRequest(
                engagement_id="eng-ctx-test",
                sender_agent_id="agent-ciso-01",
                recipient_agent_id="agent-vuln-01",
                task_id="TASK_CHILD_PROBE",
                message_type=MessageType.BRIEFING,
                content="Focus specifically on the OAuth refresh token flow on /v1/auth.",
            )
        )
        await uow.messages.send_message(
            MessageCreateRequest(
                engagement_id="eng-ctx-test",
                sender_agent_id="agent-sentinel-01",
                recipient_agent_id=None,
                task_id=None,
                message_type=MessageType.STATUS_UPDATE,
                content="Perimeter bandwidth rate limits active at 8192 kbps.",
            )
        )

        await uow.commit()

    return session_factory, engine


@pytest.mark.asyncio
async def test_context_builder_standard_assembly():
    """Verify ContextBuilder gathers role, pinned Scope/ROE, task details, ancestry, findings, and messages."""
    session_factory, engine = await setup_test_environment()
    try:
        builder = ContextBuilder(session_factory, default_token_budget=4000)
        context = await builder.build_context(
            agent_id="agent-vuln-01",
            task_id="TASK_CHILD_PROBE",
        )

        assert context.task_id == "TASK_CHILD_PROBE"
        assert context.agent_id == "agent-vuln-01"
        assert context.engagement_id == "eng-ctx-test"
        assert context.is_truncated is False

        # 1. Verify Pinned Sections are populated
        assert "agent-vuln-01" in context.system_prompt
        assert "192.168.1.0/24" in context.scope_and_roe
        assert (
            "prod-payment.securebank.local" in context.scope_and_roe
        )  # Excluded target present
        assert "DENIAL_OF_SERVICE" in context.scope_and_roe
        assert "TASK_CHILD_PROBE" in context.task_details
        assert "https://api.securebank.local/v1/auth" in context.task_details

        # 2. Verify Parent Ancestor Chain
        assert len(context.parent_chain_summaries) == 1
        assert "TASK_PARENT_MISSION" in context.parent_chain_summaries[0]

        # 3. Verify Findings (Critical finding included)
        finding_ids = [f["finding_id"] for f in context.relevant_findings]
        assert "FINDING-CRIT-01" in finding_ids

        # 4. Verify Messages
        assert len(context.recent_messages) >= 1
        assert any(
            "OAuth refresh token" in m["content"] for m in context.recent_messages
        )

        # 5. Verify ChatMessage format
        chat_messages = context.to_chat_messages()
        assert len(chat_messages) == 2
        assert chat_messages[0].role == "system"
        assert chat_messages[1].role == "user"
        assert "AUTHORIZED SCOPE & RULES OF ENGAGEMENT" in chat_messages[0].content
        assert "CURRENT TASK OBJECTIVE" in chat_messages[1].content
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_context_builder_pinned_scope_never_truncated():
    """Risk Mitigation Test: Verify that Scope and ROE constraints are pinned and NEVER truncated

    even when the token budget is severely constrained.
    """
    session_factory, engine = await setup_test_environment()
    try:
        # Set a tiny token budget of only 100 tokens (smaller than pinned content itself)
        builder = ContextBuilder(session_factory, default_token_budget=100)
        context = await builder.build_context(
            agent_id="agent-vuln-01",
            task_id="TASK_CHILD_PROBE",
            token_budget=100,
        )

        # Dynamic items should be truncated
        assert context.is_truncated is True
        assert len(context.relevant_findings) == 0
        assert len(context.recent_messages) == 0

        # Pinned Scope & ROE must remain 100% intact!
        assert "192.168.1.0/24" in context.scope_and_roe
        assert "prod-payment.securebank.local" in context.scope_and_roe
        assert "DENIAL_OF_SERVICE" in context.scope_and_roe
        assert "TASK_CHILD_PROBE" in context.task_details
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_context_builder_oversized_inputs_and_relevance_ranking():
    """Technical Decision & Acceptance Criteria: When input exceeds budget, truncation prioritizes

    high-relevance & critical findings over generic low-relevance items.
    """
    session_factory, engine = await setup_test_environment()
    try:
        # Seed 20 additional low-priority generic findings
        async with UnitOfWork(session_factory) as uow:
            for i in range(1, 21):
                await uow.findings.create_finding(
                    FindingCreateRequest(
                        finding_id=f"FINDING-GENERIC-{i}",
                        engagement_id="eng-ctx-test",
                        task_id="TASK_PARENT_MISSION",
                        agent_id="agent-recon-01",
                        title=f"Generic Banner Discovery {i}",
                        description=f"Standard banner disclosure on port {8000 + i}.",
                        severity=FindingSeverity.INFORMATIONAL,
                        target_endpoint=f"192.168.1.{i}:8000",
                    )
                )
            await uow.commit()

        # Build context with medium budget (800 tokens)
        builder = ContextBuilder(session_factory)
        context = await builder.build_context(
            agent_id="agent-vuln-01",
            task_id="TASK_CHILD_PROBE",
            token_budget=800,
        )

        assert context.is_truncated is True
        assert context.truncated_items_count > 0

        # The CRITICAL finding matching /v1/auth must be retained before generic findings
        finding_ids = [f["finding_id"] for f in context.relevant_findings]
        assert "FINDING-CRIT-01" in finding_ids
    finally:
        await engine.dispose()


def test_token_estimation_accuracy():
    """Verify token estimation helper works reliably across empty, short, and long texts."""
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello") >= 1
    long_text = "a" * 380
    assert estimate_tokens(long_text) == 100
