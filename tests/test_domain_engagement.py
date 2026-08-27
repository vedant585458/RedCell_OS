"""Unit tests for Engagement, Scope, and ROE domain models and repository."""

import pytest
from app.domain.engagement import (
    Base,
    EngagementCreateRequest,
    EngagementRepository,
    RulesOfEngagementSchema,
    TargetScopeSchema,
    TimeWindowSchema,
)
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def test_target_scope_valid_and_invalid_cidrs():
    # Valid CIDRs
    scope = TargetScopeSchema(
        allowed_ipv4_cidrs=["192.168.1.0/24", "10.0.0.1/32", "127.0.0.1"],
        allowed_domains=["*.corp.internal", "staging.lab.com"],
        allowed_ports=["80", "443", "8000-8088"],
    )
    assert len(scope.allowed_ipv4_cidrs) == 3
    assert len(scope.allowed_domains) == 2

    # Malformed CIDR must raise ValidationError
    with pytest.raises(ValidationError):
        TargetScopeSchema(allowed_ipv4_cidrs=["not_a_valid_cidr"])

    with pytest.raises(ValidationError):
        TargetScopeSchema(allowed_ipv4_cidrs=["999.999.999.999/99"])


def test_rules_of_engagement_validation():
    # Valid ROE
    roe = RulesOfEngagementSchema(
        max_intensity="vulnerability_verification",
        max_packets_per_sec=1000,
        max_concurrent_tasks=8,
    )
    assert roe.max_intensity == "vulnerability_verification"
    assert roe.max_packets_per_sec == 1000

    # Invalid intensity string must raise ValidationError
    with pytest.raises(ValidationError):
        RulesOfEngagementSchema(max_intensity="destructive_chaos")  # type: ignore[arg-type]

    # Negative rate limit must raise ValidationError
    with pytest.raises(ValidationError):
        RulesOfEngagementSchema(max_packets_per_sec=0)


@pytest.mark.asyncio
async def test_engagement_repository_crud():
    # Setup in-memory SQLite database
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = EngagementRepository(session_factory=session_factory)

    # 1. Create Engagement with nested Scope and ROE
    create_req = EngagementCreateRequest(
        engagement_id="eng-test-repo-01",
        title="Q3 Internal Security Assessment",
        organization="Acme Security Labs",
        authorized_by="Jane CISO",
        operator_id="operator-sec-01",
        time_window=TimeWindowSchema(
            valid_from_utc="2026-09-01T00:00:00Z",
            valid_until_utc="2026-09-30T23:59:59Z",
        ),
        target_scope=TargetScopeSchema(
            allowed_ipv4_cidrs=["127.0.0.1/32", "192.168.10.0/24"],
            allowed_ports=["80", "443", "8088"],
            excluded_ipv4_cidrs=["192.168.10.1/32"],
        ),
        rules_of_engagement=RulesOfEngagementSchema(
            max_intensity="vulnerability_verification",
            mandatory_approval_gates=["ACTIVE_EXPLOITATION_PROBE"],
            max_packets_per_sec=500,
        ),
    )

    created = await repo.create(create_req)
    assert created.engagement_id == "eng-test-repo-01"
    assert created.status == "CREATED"
    assert created.organization == "Acme Security Labs"
    assert len(created.target_scope.allowed_ipv4_cidrs) == 2
    assert "192.168.10.1/32" in created.target_scope.excluded_ipv4_cidrs
    assert created.rules_of_engagement.max_packets_per_sec == 500

    # 2. Read back by ID
    fetched = await repo.get_by_id("eng-test-repo-01")
    assert fetched is not None
    assert fetched.engagement_id == "eng-test-repo-01"
    assert fetched.title == "Q3 Internal Security Assessment"
    assert fetched.authorized_by == "Jane CISO"

    # 3. Update Status
    updated = await repo.update_status("eng-test-repo-01", "ACTIVE")
    assert updated is not None
    assert updated.status == "ACTIVE"

    # 4. Fetch non-existent ID returns None
    missing = await repo.get_by_id("eng-non-existent")
    assert missing is None

    await engine.dispose()
