"""Generic base repository implementing common CRUD operations.

Uses SQLAlchemy 2.x async API with the Repository Pattern to decouple
data access from business logic.
"""

import math
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base

ModelType = TypeVar("ModelType", bound=Base)


@dataclass
class PaginationResult(Generic[ModelType]):
    """Plain container for paginated query results (not a Pydantic model)."""

    items: list[Any]
    total: int
    page: int
    limit: int
    total_pages: int


class BaseRepository(Generic[ModelType]):
    """Generic async CRUD repository.

    Subclass and set `model` to the SQLAlchemy model class.
    """

    model: type[ModelType]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> ModelType:
        """Insert a new record and return the created instance."""
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def get_by_id(self, record_id: int) -> ModelType | None:
        """Fetch a single record by primary key."""
        return await self.session.get(self.model, record_id)

    async def get_all(
        self,
        page: int = 1,
        limit: int = 20,
        **filters: Any,
    ) -> PaginationResult[ModelType]:
        """Fetch paginated records with optional equality filters."""
        query = select(self.model)

        for field, value in filters.items():
            if value is not None and hasattr(self.model, field):
                query = query.where(getattr(self.model, field) == value)

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.session.execute(count_query)
        total = total_result.scalar() or 0

        offset = (page - 1) * limit
        query = query.order_by(self.model.id.asc()).offset(offset).limit(limit)
        result = await self.session.execute(query)
        items = list(result.scalars().all())

        return PaginationResult(
            items=items,
            total=total,
            page=page,
            limit=limit,
            total_pages=math.ceil(total / limit) if limit > 0 else 0,
        )

    async def update(self, record_id: int, **kwargs: Any) -> ModelType | None:
        """Update a record by ID. Returns None if not found."""
        instance = await self.get_by_id(record_id)
        if instance is None:
            return None

        for field, value in kwargs.items():
            if value is not None and hasattr(instance, field):
                setattr(instance, field, value)

        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def delete(self, record_id: int) -> bool:
        """Delete a record by ID. Returns True if deleted, False if not found."""
        instance = await self.get_by_id(record_id)
        if instance is None:
            return False

        await self.session.delete(instance)
        await self.session.flush()
        return True
