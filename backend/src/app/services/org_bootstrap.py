"""Organization bootstrap service for idempotent initialization of departments, roles, and baseline agents."""

from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.domain.agent import AgentCreateRequest, AgentStatus
from app.domain.seed import SEED_DEPARTMENTS, SEED_ROLES
from app.repositories.unit_of_work import UnitOfWork

logger = get_logger("services.org_bootstrap")


class BootstrapResult(BaseModel):
    """Summary result returned after organization hierarchy bootstrapping."""

    departments_count: int = Field(description="Total departments initialized/upserted")
    roles_count: int = Field(description="Total specialist roles initialized/upserted")
    default_agents_count: int = Field(description="Total baseline agents initialized")
    is_first_run: bool = Field(description="Whether this was the initial bootstrap on an empty DB")


# Default baseline agents to spawn on initial organizational bootstrap
DEFAULT_BASELINE_AGENTS: list[AgentCreateRequest] = [
    AgentCreateRequest(
        id="agent-ciso-01",
        role_id="role_ciso",
        department_id="dept_executive",
        display_name="Chief Information Security Officer (CISO) Agent",
        status=AgentStatus.IDLE,
        workspace_path="/data/workspaces/agent-ciso-01",
        x_coord=100,
        y_coord=100,
    ),
    AgentCreateRequest(
        id="agent-sentinel-01",
        role_id="role_safety_sentinel",
        department_id="dept_governance",
        display_name="ROE Compliance & Safety Sentinel",
        status=AgentStatus.IDLE,
        workspace_path="/data/workspaces/agent-sentinel-01",
        x_coord=100,
        y_coord=200,
    ),
    AgentCreateRequest(
        id="agent-recon-01",
        role_id="role_web_discovery",
        department_id="dept_recon",
        display_name="Web Asset Discovery Specialist",
        status=AgentStatus.IDLE,
        workspace_path="/data/workspaces/agent-recon-01",
        x_coord=300,
        y_coord=100,
    ),
    AgentCreateRequest(
        id="agent-vuln-01",
        role_id="role_web_vuln_assessor",
        department_id="dept_vulnerability",
        display_name="Web Application Security Specialist",
        status=AgentStatus.IDLE,
        workspace_path="/data/workspaces/agent-vuln-01",
        x_coord=300,
        y_coord=200,
    ),
    AgentCreateRequest(
        id="agent-report-01",
        role_id="role_technical_writer",
        department_id="dept_reporting",
        display_name="Technical Report Writer Agent",
        status=AgentStatus.IDLE,
        workspace_path="/data/workspaces/agent-report-01",
        x_coord=500,
        y_coord=100,
    ),
]


class OrgBootstrapService:
    """Service managing idempotent startup initialization of the organizational hierarchy."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    async def is_bootstrapped(self) -> bool:
        """Check whether the organization hierarchy has already been seeded."""
        async with UnitOfWork(self.session_factory) as uow:
            dept_count = await uow.departments.count()
            role_count = await uow.roles.count()
            return dept_count >= len(SEED_DEPARTMENTS) and role_count >= len(SEED_ROLES)

    async def bootstrap_organization(self, force_refresh: bool = False) -> BootstrapResult:
        """Idempotently bootstrap all departments, roles, and baseline agents.

        Safe to execute multiple times on startup with zero duplicate rows created.
        """
        is_first = not (await self.is_bootstrapped())

        logger.info(
            "Starting organization hierarchy bootstrap...",
            is_first_run=is_first,
            force_refresh=force_refresh,
        )

        async with UnitOfWork(self.session_factory) as uow:
            # 1. Upsert all 7 canonical departments
            dept_count = 0
            for dept_req in SEED_DEPARTMENTS:
                await uow.departments.upsert_department(dept_req)
                dept_count += 1

            # 2. Upsert all 16 canonical specialist roles
            role_count = 0
            for role_req in SEED_ROLES:
                await uow.roles.upsert_role(role_req)
                role_count += 1

            # 3. Initialize default baseline agents if not present
            agent_count = 0
            for agent_req in DEFAULT_BASELINE_AGENTS:
                existing = await uow.agents.get_by_id(agent_req.id)
                if not existing:
                    await uow.agents.create_agent(agent_req)
                    agent_count += 1
                elif force_refresh:
                    await uow.agents.update_status(agent_req.id, agent_req.status)
                    agent_count += 1
                else:
                    agent_count += 1

            await uow.commit()

        logger.info(
            "Organization hierarchy bootstrap completed successfully",
            departments=dept_count,
            roles=role_count,
            baseline_agents=agent_count,
        )

        return BootstrapResult(
            departments_count=dept_count,
            roles_count=role_count,
            default_agents_count=agent_count,
            is_first_run=is_first,
        )
