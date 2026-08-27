"""Unit tests for Task, TaskDependency domain models, edge relationships, and self-dependency constraints."""

import pytest
from app.domain.agent import AgentCreateRequest, AgentStatus, AIEmployeeRepository
from app.domain.department import DepartmentCreateRequest, DepartmentRepository
from app.domain.engagement import (
    Base,
    EngagementCreateRequest,
    EngagementRepository,
)
from app.domain.role import RoleCreateRequest, RoleRepository
from app.domain.task import (
    TaskCreateRequest,
    TaskRepository,
    TaskStatus,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_task_crud_and_dependency_graph():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    dept_repo = DepartmentRepository(session_factory=session_factory)
    role_repo = RoleRepository(session_factory=session_factory)
    eng_repo = EngagementRepository(session_factory=session_factory)
    agent_repo = AIEmployeeRepository(session_factory=session_factory)
    task_repo = TaskRepository(session_factory=session_factory)

    # 1. Seed Parent Context
    await dept_repo.upsert(DepartmentCreateRequest(id="dept_recon", name="Recon Dept"))
    await dept_repo.upsert(
        DepartmentCreateRequest(id="dept_vulnerability", name="Vuln Dept")
    )
    await dept_repo.upsert(
        DepartmentCreateRequest(id="dept_reporting", name="Reporting Dept")
    )

    await role_repo.upsert(
        RoleCreateRequest(
            id="role_web_discovery",
            name="Web Discovery",
            department_id="dept_recon",
            system_prompt_template="prompts/roles/web_discovery.jinja2",
        )
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
            engagement_id="eng-dag-test-01",
            title="DAG Pipeline Test Engagement",
            organization="Test Corp",
            authorized_by="Lead Architect",
        )
    )

    await agent_repo.create(
        AgentCreateRequest(
            id="agent-recon-01",
            role_id="role_web_discovery",
            department_id="dept_recon",
            display_name="Recon Agent 1",
            status=AgentStatus.IDLE,
        )
    )

    # 2. Create Task 1: Recon (Root task, 0 dependencies)
    t1 = await task_repo.create_task(
        TaskCreateRequest(
            task_id="TASK_01_RECON",
            engagement_id="eng-dag-test-01",
            department_id="dept_recon",
            title="Scan Target Attack Surface",
            assigned_role="role_web_discovery",
            priority=3,
            depends_on=[],
        )
    )
    assert t1.task_id == "TASK_01_RECON"
    assert t1.depends_on == []

    # 3. Create Task 2: Vuln Scan (Depends on Task 1)
    t2 = await task_repo.create_task(
        TaskCreateRequest(
            task_id="TASK_02_VULN_SCAN",
            engagement_id="eng-dag-test-01",
            department_id="dept_vulnerability",
            title="Analyze Discovered Endpoints",
            assigned_role="role_web_vuln_assessor",
            priority=3,
            depends_on=["TASK_01_RECON"],
            requires_approval_gate="ACTIVE_EXPLOITATION_PROBE",
        )
    )
    assert t2.task_id == "TASK_02_VULN_SCAN"
    assert t2.depends_on == ["TASK_01_RECON"]

    # 4. Create Task 3: Reporting (Depends on Task 2)
    t3 = await task_repo.create_task(
        TaskCreateRequest(
            task_id="TASK_03_REPORT",
            engagement_id="eng-dag-test-01",
            department_id="dept_reporting",
            title="Compile Assessment Report",
            assigned_role="role_technical_writer",
            priority=2,
            depends_on=["TASK_02_VULN_SCAN"],
        )
    )
    assert t3.task_id == "TASK_03_REPORT"
    assert t3.depends_on == ["TASK_02_VULN_SCAN"]

    # 5. Verify blocks-on reverse relationships
    fetched_t1 = await task_repo.get_by_id("TASK_01_RECON")
    assert fetched_t1 is not None
    assert fetched_t1.blocks == ["TASK_02_VULN_SCAN"]

    fetched_t2 = await task_repo.get_by_id("TASK_02_VULN_SCAN")
    assert fetched_t2 is not None
    assert fetched_t2.depends_on == ["TASK_01_RECON"]
    assert fetched_t2.blocks == ["TASK_03_REPORT"]

    # 6. Assign agent and transition state
    assigned = await task_repo.assign_agent("TASK_01_RECON", "agent-recon-01")
    assert assigned is not None
    assert assigned.assigned_agent_id == "agent-recon-01"
    assert assigned.status == TaskStatus.RUNNING

    completed = await task_repo.update_status("TASK_01_RECON", TaskStatus.COMPLETED)
    assert completed is not None
    assert completed.status == TaskStatus.COMPLETED

    # 7. List all tasks in engagement
    eng_tasks = await task_repo.list_by_engagement("eng-dag-test-01")
    assert len(eng_tasks) == 3

    await engine.dispose()


@pytest.mark.asyncio
async def test_self_dependency_rejection():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    eng_repo = EngagementRepository(session_factory=session_factory)
    dept_repo = DepartmentRepository(session_factory=session_factory)
    task_repo = TaskRepository(session_factory=session_factory)

    await dept_repo.upsert(DepartmentCreateRequest(id="dept_recon", name="Recon"))
    await eng_repo.create(
        EngagementCreateRequest(
            engagement_id="eng-self-dep",
            title="Self Dep Test",
            organization="Org",
            authorized_by="Lead",
        )
    )

    # Attempting to create a task that depends on itself must raise ValueError
    with pytest.raises(ValueError) as exc_info:
        await task_repo.create_task(
            TaskCreateRequest(
                task_id="TASK_LOOP_01",
                engagement_id="eng-self-dep",
                department_id="dept_recon",
                title="Self Looping Task",
                assigned_role="role_web_discovery",
                depends_on=["TASK_LOOP_01"],  # Self-dependency!
            )
        )

    assert "Self-dependency detected" in str(exc_info.value)

    await engine.dispose()
