"""Unit tests for Department, Role domain models, and taxonomy seed script."""

import pytest
from app.domain.department import DepartmentCreateRequest, DepartmentRepository
from app.domain.engagement import Base
from app.domain.role import RoleCreateRequest, RoleQuotasSchema, RoleRepository
from app.domain.seed import (
    SEED_DEPARTMENTS,
    SEED_ROLES,
    seed_departments_and_roles,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_department_and_role_crud():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    dept_repo = DepartmentRepository(session_factory=session_factory)
    role_repo = RoleRepository(session_factory=session_factory)

    # 1. Create Department
    dept = await dept_repo.upsert(
        DepartmentCreateRequest(
            id="dept_recon",
            name="Reconnaissance & OSINT Department",
            description="Perimeter mapping and intelligence gathering",
            color_theme="blue",
        )
    )
    assert dept.id == "dept_recon"
    assert dept.name == "Reconnaissance & OSINT Department"

    # 2. Create Role
    role = await role_repo.upsert(
        RoleCreateRequest(
            id="role_web_discovery",
            name="Web Asset Discovery Specialist",
            department_id="dept_recon",
            description="Crawl and map web application surface",
            capabilities=["web_crawling", "endpoint_extraction"],
            allowed_tools=["httpx", "katana", "ffuf"],
            approval_gates=[],
            quotas=RoleQuotasSchema(max_execution_time_sec=600, max_memory_mb=1024),
        )
    )
    assert role.id == "role_web_discovery"
    assert role.department_id == "dept_recon"
    assert "web_crawling" in role.capabilities
    assert "nuclei" not in role.allowed_tools
    assert "httpx" in role.allowed_tools

    # 3. Read back role and department
    fetched_dept = await dept_repo.get_by_id("dept_recon")
    assert fetched_dept is not None
    assert fetched_dept.name == "Reconnaissance & OSINT Department"

    fetched_role = await role_repo.get_by_id("role_web_discovery")
    assert fetched_role is not None
    assert fetched_role.name == "Web Asset Discovery Specialist"

    # 4. List roles in department
    dept_roles = await role_repo.list_by_department("dept_recon")
    assert len(dept_roles) == 1
    assert dept_roles[0].id == "role_web_discovery"

    await engine.dispose()


@pytest.mark.asyncio
async def test_seed_taxonomy_all_roles_and_departments():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    dept_repo = DepartmentRepository(session_factory=session_factory)
    role_repo = RoleRepository(session_factory=session_factory)

    # Run seed function
    depts_count, roles_count = await seed_departments_and_roles(session_factory)

    assert depts_count == 7
    assert roles_count == 16
    assert len(SEED_DEPARTMENTS) == 7
    assert len(SEED_ROLES) == 16

    # Verify all 7 departments exist in database
    db_depts = await dept_repo.list_all()
    assert len(db_depts) == 7
    dept_ids = {d.id for d in db_depts}
    assert "dept_executive" in dept_ids
    assert "dept_recon" in dept_ids
    assert "dept_vulnerability" in dept_ids
    assert "dept_exploitation" in dept_ids
    assert "dept_purple_telemetry" in dept_ids
    assert "dept_reporting" in dept_ids
    assert "dept_governance" in dept_ids

    # Verify all 16 roles exist in database
    db_roles = await role_repo.list_all()
    assert len(db_roles) == 16
    role_ids = {r.id for r in db_roles}

    expected_roles = [
        "role_ciso",
        "role_engagement_manager",
        "role_passive_osint",
        "role_active_network_recon",
        "role_web_discovery",
        "role_infra_vuln_assessor",
        "role_web_vuln_assessor",
        "role_cloud_container_assessor",
        "role_exploit_verifier",
        "role_privesc_credential_analyst",
        "role_adversary_emulator",
        "role_detection_analyst",
        "role_remediation_advisor",
        "role_technical_writer",
        "role_executive_briefer",
        "role_safety_sentinel",
    ]

    for role_id in expected_roles:
        assert role_id in role_ids, (
            f"Expected role '{role_id}' missing from seeded database"
        )

    # Verify role-specific tool restrictions and approval gates
    exploit_role = await role_repo.get_by_id("role_exploit_verifier")
    assert exploit_role is not None
    assert "ACTIVE_EXPLOITATION_PROBE" in exploit_role.approval_gates

    ciso_role = await role_repo.get_by_id("role_ciso")
    assert ciso_role is not None
    assert "scope_ingestion" in ciso_role.capabilities

    await engine.dispose()
