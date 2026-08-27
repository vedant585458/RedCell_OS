"""Unit and integration tests for CommandExecutionService, Scope/ROE enforcement, permission gating, and execution telemetry persistence."""

import asyncio

import pytest
from app.domain.engagement import (
    Base,
    EngagementCreateRequest,
    RulesOfEngagementSchema,
    TargetScopeSchema,
)
from app.domain.task import TaskCreateRequest, TaskStatus
from app.execution.service import (
    CommandExecutionService,
    ScopeViolationError,
    SecurityPermissionDeniedError,
    validate_target_against_scope,
)
from app.orchestrator import global_orchestrator
from app.repositories.unit_of_work import UnitOfWork
from app.services.org_bootstrap import OrgBootstrapService
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_environment():
    """Setup test SQLite database, seed org, and create engagement with strict Scope/ROE allowlists & exclusions."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    bootstrap = OrgBootstrapService(session_factory)
    await bootstrap.bootstrap_organization()

    async with UnitOfWork(session_factory) as uow:
        # Create Engagement with explicit Scope allowlists and exclusions
        await uow.engagements.create_engagement(
            EngagementCreateRequest(
                engagement_id="eng-exec-choke-test",
                title="Choke Point Execution Test Engagement",
                organization="SecureOps Financial",
                authorized_by="CISO Office",
                target_scope=TargetScopeSchema(
                    allowed_ipv4_cidrs=["192.168.1.0/24", "10.0.0.0/16"],
                    allowed_domains=["*.secureops.local", "api.secureops.local"],
                    allowed_ports=["80", "443", "8088"],
                    excluded_ipv4_cidrs=["192.168.1.254/32"],
                    excluded_domains=["prod-payment.secureops.local"],
                ),
                rules_of_engagement=RulesOfEngagementSchema(
                    max_intensity="vulnerability_verification",
                    prohibited_actions=["DENIAL_OF_SERVICE"],
                ),
            )
        )

        # 1. Recon Task (Assigned to agent-recon-01, role_web_discovery)
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_WEB_SCAN_01",
                engagement_id="eng-exec-choke-test",
                department_id="dept_recon",
                title="Web Endpoint Crawling",
                assigned_role="role_web_discovery",
                assigned_agent_id="agent-recon-01",
                input_context={"target": "https://api.secureops.local/v1"},
            )
        )
        await uow.tasks.update_status("TASK_WEB_SCAN_01", TaskStatus.RUNNING)

        # 2. Report Task (Assigned to agent-report-01, role_technical_writer)
        await uow.tasks.create_task(
            TaskCreateRequest(
                task_id="TASK_REPORT_01",
                engagement_id="eng-exec-choke-test",
                department_id="dept_reporting",
                title="Drafting Executive Summary",
                assigned_role="role_technical_writer",
                assigned_agent_id="agent-report-01",
            )
        )
        await uow.tasks.update_status("TASK_REPORT_01", TaskStatus.RUNNING)

        await uow.commit()

    return session_factory, engine


def test_validate_target_against_scope_logic():
    """Unit Test: Verify scope matching engine correctly evaluates allowlists, wildcards, CIDRs, and hard exclusions."""
    scope = TargetScopeSchema(
        allowed_ipv4_cidrs=["192.168.1.0/24", "10.0.0.0/16"],
        allowed_domains=["*.targetcorp.local", "api.targetcorp.local"],
        excluded_ipv4_cidrs=["192.168.1.254/32"],
        excluded_domains=["prod-db.targetcorp.local"],
    )

    # 1. In-Scope Targets
    in_scope_ip, _ = validate_target_against_scope("192.168.1.50", scope)
    assert in_scope_ip is True

    in_scope_domain, _ = validate_target_against_scope(
        "https://web.targetcorp.local/api", scope
    )
    assert in_scope_domain is True

    # 2. Hard Deny Exclusions
    excluded_ip, reason_ip = validate_target_against_scope("192.168.1.254", scope)
    assert excluded_ip is False
    assert "excluded CIDR" in reason_ip

    excluded_domain, reason_dom = validate_target_against_scope(
        "prod-db.targetcorp.local", scope
    )
    assert excluded_domain is False
    assert "excluded domain" in reason_dom

    # 3. Completely Out of Scope Targets
    out_of_scope_ip, _ = validate_target_against_scope("8.8.8.8", scope)
    assert out_of_scope_ip is False

    out_of_scope_dom, _ = validate_target_against_scope("malicious-domain.com", scope)
    assert out_of_scope_dom is False


@pytest.mark.asyncio
async def test_in_scope_permitted_command_execution_success():
    """Acceptance Criteria & Technical Decision: Permitted in-scope tool execution succeeds and persists records."""
    session_factory, engine = await setup_test_environment()
    try:
        service = CommandExecutionService(session_factory)

        # Execute web_crawling with tool httpx on allowlisted domain https://api.secureops.local/v1
        result = await service.execute(
            agent_id="agent-recon-01",
            capability="web_crawling",
            args={"target_url": "https://api.secureops.local/v1", "path": "/health"},
            task_id="TASK_WEB_SCAN_01",
            engagement_id="eng-exec-choke-test",
        )

        assert result.tool_id in ("httpx", "curl_probe")
        assert result.task_id == "TASK_WEB_SCAN_01"
        assert result.agent_id == "agent-recon-01"
        assert result.pid is not None

        # Verify ExecutionModel was persisted in database
        async with UnitOfWork(session_factory) as uow:
            executions = await uow.executions.list_by_task("TASK_WEB_SCAN_01")
            assert len(executions) >= 1
            exec_rec = executions[0]
            assert exec_rec.agent_id == "agent-recon-01"
            assert "api.secureops.local" in exec_rec.command.target

            # Verify audit trail
            audit_events = await uow.audit.list_by_engagement("eng-exec-choke-test")
            exec_audits = [
                e for e in audit_events if e.event_type == "command_executed"
            ]
            assert len(exec_audits) >= 1
            assert exec_audits[0].payload["task_id"] == "TASK_WEB_SCAN_01"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_out_of_scope_target_blocked_before_execution_with_audit():
    """Acceptance Criteria: Out-of-scope target is blocked before execution with an audit entry."""
    session_factory, engine = await setup_test_environment()
    try:
        service = CommandExecutionService(session_factory)
        captured_events = []

        async def capture_event(event):
            captured_events.append(event)

        global_orchestrator.register_event_subscriber(capture_event)
        await global_orchestrator.start()

        # Attempt to target forbidden excluded IP 192.168.1.254
        with pytest.raises(ScopeViolationError) as exc_info:
            await service.execute(
                agent_id="agent-recon-01",
                capability="web_crawling",
                args={"target_url": "http://192.168.1.254/secret"},
                task_id="TASK_WEB_SCAN_01",
                engagement_id="eng-exec-choke-test",
            )

        assert "OUT OF SCOPE" in str(exc_info.value)
        assert "excluded CIDR" in str(exc_info.value)

        await asyncio.sleep(0.05)

        # Verify Immutable Audit Store recorded scope violation
        async with UnitOfWork(session_factory) as uow:
            audit_events = await uow.audit.list_by_engagement("eng-exec-choke-test")
            violations = [
                e for e in audit_events if e.event_type == "scope_violation_blocked"
            ]
            assert len(violations) >= 1
            assert violations[0].payload["target"] == "http://192.168.1.254/secret"
            assert violations[0].payload["agent_id"] == "agent-recon-01"

        # Verify orchestrator alert emitted
        event_types = [e.event_type for e in captured_events]
        assert "scope_violation_blocked" in event_types
    finally:
        global_orchestrator.unregister_event_subscriber(capture_event)
        await global_orchestrator.stop()
        await engine.dispose()


@pytest.mark.asyncio
async def test_unpermitted_capability_blocked_by_permission_checker():
    """Testing: Verify agent attempting an unpermitted action (e.g. Technical Writer running active port scans) is blocked."""
    session_factory, engine = await setup_test_environment()
    try:
        service = CommandExecutionService(session_factory)

        # Technical Writer (agent-report-01) attempting active_scan capability
        with pytest.raises(SecurityPermissionDeniedError) as exc_info:
            await service.execute(
                agent_id="agent-report-01",
                capability="active_scan",
                args={"target": "192.168.1.50"},
                task_id="TASK_REPORT_01",
                engagement_id="eng-exec-choke-test",
            )

        assert "SECURITY PERMISSION DENIED" in str(exc_info.value)

        # Verify audit store recorded permission block
        async with UnitOfWork(session_factory) as uow:
            audit_events = await uow.audit.list_by_engagement("eng-exec-choke-test")
            perm_blocks = [
                e
                for e in audit_events
                if e.event_type == "permission_violation_blocked"
            ]
            assert len(perm_blocks) >= 1
            assert perm_blocks[0].payload["role_id"] == "role_technical_writer"
    finally:
        await engine.dispose()
