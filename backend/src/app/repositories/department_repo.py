"""Concrete Department repository wrapping SQLAlchemy session."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.department import (
    DepartmentCreateRequest,
    DepartmentModel,
    DepartmentResponse,
)
from app.repositories.base import BaseRepository


class DepartmentRepository(BaseRepository[DepartmentModel, str]):
    """Typed repository for Department entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(DepartmentModel, session)

    async def upsert_department(self, req: DepartmentCreateRequest) -> DepartmentResponse:
        now = datetime.now(UTC).isoformat()
        model = await self.get_by_id(req.id)
        if model:
            model.name = req.name
            model.description = req.description
            model.parent_org = req.parent_org
            model.color_theme = req.color_theme
        else:
            model = DepartmentModel(
                id=req.id,
                name=req.name,
                description=req.description,
                parent_org=req.parent_org,
                color_theme=req.color_theme,
                created_at=now,
            )
            self.session.add(model)
        await self.session.flush()
        return model.to_response()

    async def list_departments(self) -> list[DepartmentResponse]:
        stmt = select(DepartmentModel).order_by(DepartmentModel.id)
        res = await self.session.execute(stmt)
        return [row.to_response() for row in res.scalars().all()]
