"""Unit tests for the PermissionChecker deny-by-default role permission evaluation and audit logging."""

import pytest
from app.domain.engagement import Base, EngagementCreateRequest
from app.permissions.checker import PermissionChecker
from app.permissions.models import PermissionCheckRequest
from app.repositories.unit_of_work import UnitOfWork
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with UnitOfWork(session_factory) as uow:
        await uow.engagements.create_engagement(
            EngagementCreateRequest(
                engagement_id="eng-perm-test",
                title="Permission Security Test",
                organization="Acme Labs",
                authorized_by="Lead CISO",
            )
        )
        await uow.commit()

    return session_factory, engine


@pytest.mark.asyncio
async def test_permission_allowed_path():
    session_factory, engine = await setup_test_db()
    try:
        checker = PermissionChecker(session_factory=session_factory)

        req = PermissionCheckRequest(
            agent_id="agent-recon-01",
            role_id="role_active_network_recon",
            department_id="dept_recon",
            tool_id="nmap",
            target="127.0.0.1:8088",
            action_category="active_scan",
            engagement_id="eng-perm-test",
            correlation_id="corr-perm-01",
        )

        result = await checker.evaluate_permission(req)

        assert result.allowed is True
        assert result.violating_permission is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_permission_denied_passive_role_active_scan():
    session_factory, engine = await setup_test_db()
    try:
        checker = PermissionChecker(session_factory=session_factory)

        # Passive OSINT role attempting active port scan
        req = PermissionCheckRequest(
            agent_id="agent-osint-01",
            role_id="role_passive_osint",
            department_id="dept_recon",
            tool_id="nmap",
            target="127.0.0.1",
            action_category="active_scan",
            engagement_id="eng-perm-test",
            correlation_id="corr-perm-deny-01",
        )

        result = await checker.evaluate_permission(req)

        assert result.allowed is False
        assert result.violating_permission == "can_execute_active_scan"
        assert "not permitted to execute active network/port scans" in result.reason

        # Verify audit log recorded violation
        async with UnitOfWork(session_factory) as uow:
            audits = await uow.audit.list_by_engagement("eng-perm-test")
            assert len(audits) >= 1
            deny_event = next(
                a for a in audits if a.event_type == "permission_violation_blocked"
            )
            assert (
                deny_event.payload["violating_permission"] == "can_execute_active_scan"
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_permission_denied_technical_writer_exploit_poc():
    session_factory, engine = await setup_test_db()
    try:
        checker = PermissionChecker(session_factory=session_factory)

        # Report writer role attempting exploit PoC
        req = PermissionCheckRequest(
            agent_id="agent-report-01",
            role_id="role_technical_writer",
            department_id="dept_reporting",
            tool_id="python_poc_runner",
            target="127.0.0.1:8088",
            action_category="exploit_poc",
            engagement_id="eng-perm-test",
            correlation_id="corr-perm-deny-02",
        )

        result = await checker.evaluate_permission(req)

        assert result.allowed is False
        assert result.violating_permission == "can_execute_exploit_poc"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_permission_gated_approval_trigger():
    session_factory, engine = await setup_test_db()
    try:
        checker = PermissionChecker(session_factory=session_factory)

        # Exploit verifier executing PoC is permitted, but triggers mandatory approval gate
        req = PermissionCheckRequest(
            agent_id="agent-exploit-01",
            role_id="role_exploit_verifier",
            department_id="dept_exploitation",
            tool_id="python_poc_runner",
            target="http://127.0.0.1:8088/api/v1/debug/config",
            action_category="exploit_poc",
            engagement_id="eng-perm-test",
            correlation_id="corr-perm-gate-01",
        )

        result = await checker.evaluate_permission(req)

        assert result.allowed is True
        assert result.requires_approval is True
        assert result.triggered_gate_category == "ACTIVE_EXPLOITATION_PROBE"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_permission_deny_by_default_unknown_role_or_tool():
    session_factory, engine = await setup_test_db()
    try:
        checker = PermissionChecker(session_factory=session_factory)

        # 1. Unknown role
        req1 = PermissionCheckRequest(
            agent_id="agent-rogue-01",
            role_id="role_unregistered_hacker",
            department_id="dept_recon",
            tool_id="nmap",
            target="127.0.0.1",
            action_category="active_scan",
            engagement_id="eng-perm-test",
            correlation_id="corr-perm-deny-03",
        )
        res1 = await checker.evaluate_permission(req1)
        assert res1.allowed is False
        assert res1.violating_permission == "role_undefined"

        # 2. Unregistered tool
        req2 = PermissionCheckRequest(
            agent_id="agent-recon-01",
            role_id="role_active_network_recon",
            department_id="dept_recon",
            tool_id="malicious_unregistered_binary",
            target="127.0.0.1",
            action_category="active_scan",
            engagement_id="eng-perm-test",
            correlation_id="corr-perm-deny-04",
        )
        res2 = await checker.evaluate_permission(req2)
        assert res2.allowed is False
        assert res2.violating_permission == "tool_unregistered"
    finally:
        await engine.dispose()
