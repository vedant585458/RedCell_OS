"""Department domain model, Pydantic schemas, and SQLAlchemy ORM entity."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.engagement import Base


class DepartmentCreateRequest(BaseModel):
    """Payload to create or register a department."""

    id: str = Field(
        ...,
        min_length=2,
        max_length=64,
        description="Unique department identifier (e.g. dept_recon)",
    )
    name: str = Field(..., min_length=2, max_length=128)
    description: str = Field(default="")
    parent_org: str = Field(default="RedCell_OS Operations")
    color_theme: str = Field(default="blue")


class DepartmentResponse(BaseModel):
    """Outbound API response representing a department."""

    id: str
    name: str
    description: str
    parent_org: str
    color_theme: str
    created_at: str


class DepartmentModel(Base):
    """SQLAlchemy relational table mapping for Departments."""

    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    parent_org: Mapped[str] = mapped_column(
        String(128), nullable=False, default="RedCell_OS Operations"
    )
    color_theme: Mapped[str] = mapped_column(String(32), nullable=False, default="blue")
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)

    def to_response(self) -> DepartmentResponse:
        return DepartmentResponse(
            id=str(self.id),
            name=str(self.name),
            description=str(self.description),
            parent_org=str(self.parent_org),
            color_theme=str(self.color_theme),
            created_at=str(self.created_at),
        )


class DepartmentRepository:
    """Repository handling CRUD operations for Departments."""

    def __init__(self, session_factory: Any) -> None:
        self.session_factory = session_factory

    async def upsert(self, req: DepartmentCreateRequest) -> DepartmentResponse:
        """Create or update a department entity."""
        now = datetime.now(UTC).isoformat()
        async with self.session_factory() as session:
            async with session.begin():
                model = await session.get(DepartmentModel, req.id)
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
                    session.add(model)
            await session.commit()
            return model.to_response()

    async def get_by_id(self, dept_id: str) -> DepartmentResponse | None:
        """Fetch department by its ID."""
        async with self.session_factory() as session:
            model = await session.get(DepartmentModel, dept_id)
            if model:
                return model.to_response()
            return None

    async def list_all(self) -> list[DepartmentResponse]:
        """List all registered departments."""
        async with self.session_factory() as session:
            from sqlalchemy import select

            stmt = select(DepartmentModel).order_by(DepartmentModel.id)
            result = await session.execute(stmt)
            return [row.to_response() for row in result.scalars()]
