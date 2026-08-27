"""Role domain model, Pydantic schemas, and SQLAlchemy ORM entity."""

import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.engagement import Base


class RoleQuotasSchema(BaseModel):
    """Resource and execution quotas for an agent role."""

    max_execution_time_sec: int = Field(default=600, ge=10, le=3600)
    max_memory_mb: int = Field(default=1024, ge=128, le=16384)
    max_network_bandwidth_kbps: int = Field(default=4096, ge=64)
    max_concurrent_subprocesses: int = Field(default=2, ge=1, le=16)


class RoleCreateRequest(BaseModel):
    """Payload to register or update a specialist role."""

    id: str = Field(
        ...,
        min_length=2,
        max_length=64,
        description="Unique role identifier (e.g. role_web_vuln_assessor)",
    )
    name: str = Field(..., min_length=2, max_length=128)
    department_id: str = Field(..., description="Parent department ID (e.g. dept_vulnerability)")
    description: str = Field(default="")
    version: str = Field(default="1.0.0")
    system_prompt_template: str = Field(default="prompts/roles/default.jinja2")
    capabilities: list[str] = Field(
        default_factory=list, description="Structured list of domain capabilities"
    )
    allowed_tools: list[str] = Field(
        default_factory=list, description="Allowlisted tool binaries (e.g. nuclei, nmap)"
    )
    approval_gates: list[str] = Field(default_factory=list, description="Triggered gate categories")
    quotas: RoleQuotasSchema = Field(default_factory=RoleQuotasSchema)


class RoleResponse(BaseModel):
    """Outbound API response representing a specialist role."""

    id: str
    name: str
    department_id: str
    description: str
    version: str
    system_prompt_template: str
    capabilities: list[str]
    allowed_tools: list[str]
    approval_gates: list[str]
    quotas: RoleQuotasSchema
    created_at: str


class RoleModel(Base):
    """SQLAlchemy relational table mapping for Specialist Roles."""

    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    department_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("departments.id"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    system_prompt_template: Mapped[str] = mapped_column(String(256), nullable=False)

    capabilities_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    allowed_tools_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    approval_gates_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    quotas_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    created_at: Mapped[str] = mapped_column(String(64), nullable=False)

    def to_response(self) -> RoleResponse:
        """Convert ORM model to validated Pydantic RoleResponse."""
        try:
            capabilities = json.loads(str(self.capabilities_json))
        except Exception:
            capabilities = []

        try:
            allowed_tools = json.loads(str(self.allowed_tools_json))
        except Exception:
            allowed_tools = []

        try:
            approval_gates = json.loads(str(self.approval_gates_json))
        except Exception:
            approval_gates = []

        try:
            quotas_dict = json.loads(str(self.quotas_json))
            quotas = RoleQuotasSchema(**quotas_dict)
        except Exception:
            quotas = RoleQuotasSchema()

        return RoleResponse(
            id=str(self.id),
            name=str(self.name),
            department_id=str(self.department_id),
            description=str(self.description),
            version=str(self.version),
            system_prompt_template=str(self.system_prompt_template),
            capabilities=capabilities,
            allowed_tools=allowed_tools,
            approval_gates=approval_gates,
            quotas=quotas,
            created_at=str(self.created_at),
        )


class RoleRepository:
    """Repository handling CRUD operations for Specialist Roles."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    async def upsert(self, req: RoleCreateRequest) -> RoleResponse:
        """Create or update a specialist role."""
        now = datetime.now(UTC).isoformat()
        async with self.session_factory() as session:
            async with session.begin():
                model = await session.get(RoleModel, req.id)
                if model:
                    model.name = req.name
                    model.department_id = req.department_id
                    model.description = req.description
                    model.version = req.version
                    model.system_prompt_template = req.system_prompt_template
                    model.capabilities_json = json.dumps(req.capabilities)
                    model.allowed_tools_json = json.dumps(req.allowed_tools)
                    model.approval_gates_json = json.dumps(req.approval_gates)
                    model.quotas_json = json.dumps(req.quotas.model_dump())
                else:
                    model = RoleModel(
                        id=req.id,
                        name=req.name,
                        department_id=req.department_id,
                        description=req.description,
                        version=req.version,
                        system_prompt_template=req.system_prompt_template,
                        capabilities_json=json.dumps(req.capabilities),
                        allowed_tools_json=json.dumps(req.allowed_tools),
                        approval_gates_json=json.dumps(req.approval_gates),
                        quotas_json=json.dumps(req.quotas.model_dump()),
                        created_at=now,
                    )
                    session.add(model)
            await session.commit()
            return model.to_response()

    async def get_by_id(self, role_id: str) -> RoleResponse | None:
        """Fetch role by its ID."""
        async with self.session_factory() as session:
            model = await session.get(RoleModel, role_id)
            if model:
                return model.to_response()
            return None

    async def list_by_department(self, dept_id: str) -> list[RoleResponse]:
        """List all roles in a given department."""
        async with self.session_factory() as session:
            from sqlalchemy import select

            stmt = (
                select(RoleModel).where(RoleModel.department_id == dept_id).order_by(RoleModel.id)
            )
            result = await session.execute(stmt)
            return [row.to_response() for row in result.scalars()]

    async def list_all(self) -> list[RoleResponse]:
        """List all registered roles."""
        async with self.session_factory() as session:
            from sqlalchemy import select

            stmt = select(RoleModel).order_by(RoleModel.id)
            result = await session.execute(stmt)
            return [row.to_response() for row in result.scalars()]
