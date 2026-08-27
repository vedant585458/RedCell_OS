"""Integration tests for Engagement intake REST API endpoints and ROE validation."""

import httpx
import pytest
from app.api.engagements import get_uow_dependency
from app.domain.engagement import Base
from app.main import create_app
from app.repositories.unit_of_work import UnitOfWork
from app.services.intake import EngagementIntakeRequest, EngagementIntakeService
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_app_and_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app()
    app.dependency_overrides[get_uow_dependency] = lambda: session_factory

    return app, session_factory, engine


@pytest.mark.asyncio
async def test_engagement_intake_service_success():
    _app, session_factory, engine = await setup_test_app_and_session()
    try:
        service = EngagementIntakeService(session_factory=session_factory)

        req = EngagementIntakeRequest(
            engagement_id="eng-intake-test-01",
            title="Q3 External Pentest",
            organization="Acme Financial",
            authorized_by="Jane Doe, CISO",
            operator_id="op-vedant",
            high_level_objective="Audit staging portal perimeter",
            target_scope={
                "allowed_ipv4_cidrs": ["127.0.0.1/32", "10.0.50.0/24"],
                "allowed_domains": ["staging.acme.local"],
                "allowed_ports": ["80", "443", "8088"],
                "excluded_ipv4_cidrs": ["10.0.50.1/32"],
            },
            rules_of_engagement={
                "max_intensity": "vulnerability_verification",
                "mandatory_approval_gates": ["ACTIVE_EXPLOITATION_PROBE"],
                "max_packets_per_sec": 500,
            },
        )

        created = await service.intake_engagement(req)
        assert created.engagement_id == "eng-intake-test-01"
        assert created.title == "Q3 External Pentest"
        assert created.status == "CREATED"
        assert len(created.target_scope.allowed_ipv4_cidrs) == 2
        assert "10.0.50.1/32" in created.target_scope.excluded_ipv4_cidrs

        # Verify audit event and DB persistence in UnitOfWork
        async with UnitOfWork(session_factory) as uow:
            assert await uow.engagements.exists("eng-intake-test-01") is True
            audit_events = await uow.audit.list_by_engagement("eng-intake-test-01")
            assert len(audit_events) >= 1
            assert audit_events[0].event_type == "engagement_created"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_engagement_intake_empty_scope_rejection():
    _app, session_factory, engine = await setup_test_app_and_session()
    try:
        service = EngagementIntakeService(session_factory=session_factory)

        # Empty scope with zero targets must be rejected
        req = EngagementIntakeRequest(
            engagement_id="eng-bad-scope",
            title="Invalid Scope Pentest",
            organization="Acme",
            authorized_by="CISO",
            target_scope={
                "allowed_ipv4_cidrs": [],
                "allowed_domains": [],
                "allowed_ports": ["80"],
            },
        )

        with pytest.raises(ValueError) as exc_info:
            await service.intake_engagement(req)

        assert "At least one allowlisted target" in str(exc_info.value)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_engagement_rest_api_endpoints():
    app, _session_factory, engine = await setup_test_app_and_session()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 1. POST /api/v1/engagements
            payload = {
                "engagement_id": "eng-api-post-01",
                "title": "API Intake Test",
                "organization": "Target Org",
                "authorized_by": "Security Lead",
                "operator_id": "op-01",
                "target_scope": {
                    "allowed_ipv4_cidrs": ["127.0.0.1/32"],
                    "allowed_ports": ["8088"],
                },
                "rules_of_engagement": {
                    "max_intensity": "vulnerability_verification",
                },
            }

            post_res = await client.post("/api/v1/engagements", json=payload)
            assert post_res.status_code == 201
            data = post_res.json()
            assert data["engagement_id"] == "eng-api-post-01"
            assert data["status"] == "CREATED"

            # 2. GET /api/v1/engagements
            list_res = await client.get("/api/v1/engagements")
            assert list_res.status_code == 200
            list_data = list_res.json()
            assert len(list_data) >= 1
            assert list_data[0]["engagement_id"] == "eng-api-post-01"

            # 3. GET /api/v1/engagements/{id}
            get_res = await client.get("/api/v1/engagements/eng-api-post-01")
            assert get_res.status_code == 200
            assert get_res.json()["title"] == "API Intake Test"

            # 4. Non-existent returns 404
            bad_get = await client.get("/api/v1/engagements/eng-non-existent")
            assert bad_get.status_code == 404
    finally:
        await engine.dispose()
