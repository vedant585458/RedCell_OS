"""Concrete Role repository wrapping SQLAlchemy session."""

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.role import (
    RoleCreateRequest,
    RoleModel,
    RoleResponse,
)
from app.repositories.base import BaseRepository


class RoleRepository(BaseRepository[RoleModel, str]):
    """Typed repository for Role entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(RoleModel, session)

    async def upsert_role(self, req: RoleCreateRequest) -> RoleResponse:
        now = datetime.now(UTC).isoformat()
        model = await self.get_by_id(req.id)
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
            self.session.add(model)
        await self.session.flush()
        return model.to_response()

    async def list_by_department(self, dept_id: str) -> list[RoleResponse]:
        stmt = select(RoleModel).where(RoleModel.department_id == dept_id).order_by(RoleModel.id)
        res = await self.session.execute(stmt)
        return [row.to_response() for row in res.scalars().all()]

    async def list_roles(self) -> list[RoleResponse]:
        stmt = select(RoleModel).order_by(RoleModel.id)
        res = await self.session.execute(stmt)
        return [row.to_response() for row in res.scalars().all()]
