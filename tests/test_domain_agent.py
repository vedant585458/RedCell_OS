"""Unit tests for AIEmployee (Agent) domain models, status indexing, and repository layer."""

import pytest
from app.domain.agent import (
    AgentCreateRequest,
    AgentStatus,
    AIEmployeeRepository,
)
from app.domain.department import DepartmentCreateRequest, DepartmentRepository
from app.domain.engagement import Base
from app.domain.role import RoleCreateRequest, RoleRepository
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_ai_employee_crud_and_status_transitions():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    dept_repo = DepartmentRepository(session_factory=session_factory)
    role_repo = RoleRepository(session_factory=session_factory)
    agent_repo = AIEmployeeRepository(session_factory=session_factory)

    # 1. Seed Parent Department & Role
    await dept_repo.upsert(
        DepartmentCreateRequest(
            id="dept_vulnerability",
            name="Vulnerability Assessment",
            description="Security Auditing",
        )
    )
    await role_repo.upsert(
        RoleCreateRequest(
            id="role_web_vuln_assessor",
            name="Web Application Security Specialist",
            department_id="dept_vulnerability",
            system_prompt_template="prompts/roles/web_vuln_assessor.jinja2",
            capabilities=["owasp_top10"],
            allowed_tools=["nuclei", "httpx"],
        )
    )

    # 2. Create AI Employee (Agent)
    agent_req = AgentCreateRequest(
        id="agent-vuln-01",
        role_id="role_web_vuln_assessor",
        department_id="dept_vulnerability",
        display_name="Vuln Assessor Agent Prime",
        status=AgentStatus.IDLE,
        workspace_path="/data/workspaces/agent-vuln-01",
        x_coord=200,
        y_coord=150,
    )

    created = await agent_repo.create(agent_req)
    assert created.id == "agent-vuln-01"
    assert created.role_id == "role_web_vuln_assessor"
    assert created.department_id == "dept_vulnerability"
    assert created.status == AgentStatus.IDLE
    assert created.x_coord == 200
    assert created.y_coord == 150

    # 3. Read back by ID
    fetched = await agent_repo.get_by_id("agent-vuln-01")
    assert fetched is not None
    assert fetched.display_name == "Vuln Assessor Agent Prime"

    # 4. Query by Status
    idle_agents = await agent_repo.list_by_status(AgentStatus.IDLE)
    assert len(idle_agents) == 1
    assert idle_agents[0].id == "agent-vuln-01"

    executing_agents = await agent_repo.list_by_status(AgentStatus.EXECUTING)
    assert len(executing_agents) == 0

    # 5. Status Transition: IDLE -> PLANNING -> EXECUTING
    updated = await agent_repo.update_status(
        agent_id="agent-vuln-01",
        status=AgentStatus.EXECUTING,
        current_task_id="TASK-VULN-001",
    )
    assert updated is not None
    assert updated.status == AgentStatus.EXECUTING
    assert updated.current_task_id == "TASK-VULN-001"

    # Verify query by status reflects transition
    executing_agents = await agent_repo.list_by_status(AgentStatus.EXECUTING)
    assert len(executing_agents) == 1

    # 6. Update 2D Office Coordinates
    moved = await agent_repo.update_position("agent-vuln-01", 320, 480)
    assert moved is not None
    assert moved.x_coord == 320
    assert moved.y_coord == 480

    # 7. Query by Department
    dept_agents = await agent_repo.list_by_department("dept_vulnerability")
    assert len(dept_agents) == 1
    assert dept_agents[0].id == "agent-vuln-01"

    await engine.dispose()
