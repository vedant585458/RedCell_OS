"""Generic BaseRepository class providing typed CRUD and session abstractions."""

from typing import Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

ModelT = TypeVar("ModelT")
IdT = TypeVar("IdT")


class BaseRepository(Generic[ModelT, IdT]):
    """Generic async repository providing standard data access primitives."""

    def __init__(self, model_cls: type[ModelT], session: AsyncSession) -> None:
        self.model_cls = model_cls
        self.session = session

    async def get_by_id(self, id_val: IdT) -> ModelT | None:
        """Fetch entity by primary key."""
        return await self.session.get(self.model_cls, id_val)

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[ModelT]:
        """List entities with pagination."""
        stmt = select(self.model_cls).limit(limit).offset(offset)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def add(self, entity: ModelT) -> ModelT:
        """Add new entity to session."""
        self.session.add(entity)
        return entity

    async def delete(self, id_val: IdT) -> bool:
        """Delete entity by ID if present."""
        entity = await self.get_by_id(id_val)
        if entity:
            await self.session.delete(entity)
            return True
        return False

    async def count(self) -> int:
        """Return total count of entities."""
        stmt = select(func.count()).select_from(self.model_cls)
        res = await self.session.execute(stmt)
        return int(res.scalar() or 0)

    async def exists(self, id_val: IdT) -> bool:
        """Check if entity exists by ID."""
        entity = await self.get_by_id(id_val)
        return entity is not None
