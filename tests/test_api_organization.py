"""Integration tests for the organization hierarchy query API."""

import httpx
import pytest
from app.api.organization import get_uow_dependency
from app.domain.engagement import Base
from app.main import create_app
from app.services.org_bootstrap import OrgBootstrapService
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_get_organization_hierarchy():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    bootstrap = OrgBootstrapService(session_factory)
    await bootstrap.bootstrap_organization()

    app = create_app()
    app.dependency_overrides[get_uow_dependency] = lambda: session_factory

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get("/api/v1/organization")
        assert res.status_code == 200
        data = res.json()

        assert data["organization_name"] == "RedCell_OS Cyber Operations"
        assert data["total_departments"] == 7
        assert data["total_roles"] == 16
        assert data["total_employees"] == 5
        assert len(data["departments"]) == 7

        # Verify executive department has CISO role and agent
        exec_dept = next(d for d in data["departments"] if d["id"] == "dept_executive")
        assert exec_dept["name"] == "Executive Leadership & Strategy"
        assert exec_dept["employee_count"] == 1
        assert exec_dept["employees"][0]["id"] == "agent-ciso-01"

    await engine.dispose()


@pytest.mark.asyncio
async def test_list_departments_endpoint():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    bootstrap = OrgBootstrapService(session_factory)
    await bootstrap.bootstrap_organization()

    app = create_app()
    app.dependency_overrides[get_uow_dependency] = lambda: session_factory

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get("/api/v1/organization/departments")
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 7
        dept_ids = {d["id"] for d in data}
        assert "dept_recon" in dept_ids
        assert "dept_vulnerability" in dept_ids

    await engine.dispose()


@pytest.mark.asyncio
async def test_list_department_employees_endpoint():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    bootstrap = OrgBootstrapService(session_factory)
    await bootstrap.bootstrap_organization()

    app = create_app()
    app.dependency_overrides[get_uow_dependency] = lambda: session_factory

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. Valid department
        res = await client.get("/api/v1/organization/departments/dept_recon/employees")
        assert res.status_code == 200
        data = res.json()
        assert len(data) >= 1
        assert data[0]["id"] == "agent-recon-01"

        # 2. Non-existent department returns 404
        bad_res = await client.get(
            "/api/v1/organization/departments/dept_non_existent/employees"
        )
        assert bad_res.status_code == 404

    await engine.dispose()


@pytest.mark.asyncio
async def test_list_roles_endpoint():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    bootstrap = OrgBootstrapService(session_factory)
    await bootstrap.bootstrap_organization()

    app = create_app()
    app.dependency_overrides[get_uow_dependency] = lambda: session_factory

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. All roles
        res = await client.get("/api/v1/organization/roles")
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 16

        # 2. Filter by department
        recon_res = await client.get(
            "/api/v1/organization/roles?department_id=dept_recon"
        )
        recon_roles = recon_res.json()
        assert len(recon_roles) == 3
        role_ids = {r["id"] for r in recon_roles}
        assert "role_web_discovery" in role_ids
        assert "role_active_network_recon" in role_ids
        assert "role_passive_osint" in role_ids

    await engine.dispose()
