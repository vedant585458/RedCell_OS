"""REST API endpoints for querying organizational hierarchy, departments, roles, and AI employees."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.agent import AgentResponse
from app.domain.department import DepartmentResponse
from app.domain.role import RoleResponse
from app.repositories.unit_of_work import UnitOfWork
from app.storage.database import get_session_factory

router = APIRouter(prefix="/api/v1/organization", tags=["organization", "hierarchy"])


class DepartmentWithEmployeesResponse(BaseModel):
    """Department entity bundled with its assigned specialist roles and AI employees."""

    id: str
    name: str
    description: str
    parent_org: str
    color_theme: str
    created_at: str
    employee_count: int = Field(description="Total active employees in this department")
    employees: list[AgentResponse] = Field(default_factory=list)
    roles: list[RoleResponse] = Field(default_factory=list)


class OrganizationHierarchyResponse(BaseModel):
    """Complete organizational structure tree representation."""

    organization_name: str = Field(default="RedCell_OS Cyber Operations")
    total_departments: int
    total_roles: int
    total_employees: int
    departments: list[DepartmentWithEmployeesResponse]


def get_uow_dependency() -> async_sessionmaker[AsyncSession]:
    return get_session_factory()


@router.get("", response_model=OrganizationHierarchyResponse)
async def get_organization_hierarchy(
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_uow_dependency),
) -> OrganizationHierarchyResponse:
    """Retrieve the complete organizational hierarchy tree (departments -> roles -> employees).

    Returns a structured flat-with-references model allowing flexible client-side
    graph rendering in the 2D office simulation and command center dashboard.
    """
    async with UnitOfWork(session_factory) as uow:
        departments = await uow.departments.list_departments()
        roles = await uow.roles.list_roles()
        agents = await uow.agents.list_agents()

    # Index roles and employees by department ID
    roles_by_dept: dict[str, list[RoleResponse]] = {}
    for r in roles:
        roles_by_dept.setdefault(r.department_id, []).append(r)

    agents_by_dept: dict[str, list[AgentResponse]] = {}
    for a in agents:
        agents_by_dept.setdefault(a.department_id, []).append(a)

    dept_trees: list[DepartmentWithEmployeesResponse] = []
    for d in departments:
        dept_roles = roles_by_dept.get(d.id, [])
        dept_agents = agents_by_dept.get(d.id, [])
        dept_trees.append(
            DepartmentWithEmployeesResponse(
                id=d.id,
                name=d.name,
                description=d.description,
                parent_org=d.parent_org,
                color_theme=d.color_theme,
                created_at=d.created_at,
                employee_count=len(dept_agents),
                employees=dept_agents,
                roles=dept_roles,
            )
        )

    return OrganizationHierarchyResponse(
        organization_name="RedCell_OS Cyber Operations",
        total_departments=len(departments),
        total_roles=len(roles),
        total_employees=len(agents),
        departments=dept_trees,
    )


@router.get("/departments", response_model=list[DepartmentResponse])
async def list_departments(
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_uow_dependency),
) -> list[DepartmentResponse]:
    """List all registered departments."""
    async with UnitOfWork(session_factory) as uow:
        return await uow.departments.list_departments()


@router.get("/departments/{department_id}/employees", response_model=list[AgentResponse])
async def list_department_employees(
    department_id: str,
    limit: int = Query(
        default=50, ge=1, le=500, description="Pagination limit for large agent fleets"
    ),
    offset: int = Query(default=0, ge=0),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_uow_dependency),
) -> list[AgentResponse]:
    """List employees within a specific department with pagination support."""
    async with UnitOfWork(session_factory) as uow:
        dept = await uow.departments.get_by_id(department_id)
        if not dept:
            raise HTTPException(status_code=404, detail=f"Department '{department_id}' not found")
        agents = await uow.agents.list_by_department(department_id)
        return agents[offset : offset + limit]


@router.get("/roles", response_model=list[RoleResponse])
async def list_specialist_roles(
    department_id: str | None = Query(default=None, description="Optional department filter"),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_uow_dependency),
) -> list[RoleResponse]:
    """List all specialist roles with their tool allowlists and capabilities."""
    async with UnitOfWork(session_factory) as uow:
        if department_id:
            return await uow.roles.list_by_department(department_id)
        return await uow.roles.list_roles()
