"""Integration tests for OrgBootstrapService and idempotent organizational seeding."""

import pytest
from app.domain.engagement import Base
from app.repositories.unit_of_work import UnitOfWork
from app.services.org_bootstrap import OrgBootstrapService
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def setup_test_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


@pytest.mark.asyncio
async def test_org_bootstrap_first_run_and_idempotency():
    session_factory, engine = await setup_test_db()
    try:
        service = OrgBootstrapService(session_factory=session_factory)

        # 1. Verify initially not bootstrapped
        assert await service.is_bootstrapped() is False

        # 2. First Run Bootstrap
        result1 = await service.bootstrap_organization()
        assert result1.is_first_run is True
        assert result1.departments_count == 7
        assert result1.roles_count == 16
        assert result1.default_agents_count == 5

        # Verify is_bootstrapped is now True
        assert await service.is_bootstrapped() is True

        # 3. Verify Database Contents
        async with UnitOfWork(session_factory) as uow:
            assert await uow.departments.count() == 7
            assert await uow.roles.count() == 16
            assert await uow.agents.count() == 5

            # Verify CISO agent exists
            ciso = await uow.agents.get_agent_response("agent-ciso-01")
            assert ciso is not None
            assert ciso.role_id == "role_ciso"
            assert ciso.department_id == "dept_executive"

            # Verify Sentinel agent exists
            sentinel = await uow.agents.get_agent_response("agent-sentinel-01")
            assert sentinel is not None
            assert sentinel.role_id == "role_safety_sentinel"
            assert sentinel.department_id == "dept_governance"

        # 4. Second Run (Idempotency check: must not duplicate or fail)
        result2 = await service.bootstrap_organization()
        assert result2.is_first_run is False
        assert result2.departments_count == 7
        assert result2.roles_count == 16
        assert result2.default_agents_count == 5

        # Verify counts remain strictly identical
        async with UnitOfWork(session_factory) as uow:
            assert await uow.departments.count() == 7
            assert await uow.roles.count() == 16
            assert await uow.agents.count() == 5

    finally:
        await engine.dispose()
