"""Workspace repository handling workspace queries and pagination."""

import math

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace import Workspace, WorkspaceMember
from app.repositories.base import BaseRepository, PaginationResult


class WorkspaceRepository(BaseRepository[Workspace]):
    """Repository managing Workspace entity persistence."""

    model = Workspace

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_for_user(
        self,
        user_id: int,
        page: int = 1,
        limit: int = 20,
    ) -> PaginationResult[Workspace]:
        """Fetch paginated workspaces where the given user is owner or member."""
        member_subquery = (
            select(WorkspaceMember.workspace_id)
            .where(WorkspaceMember.user_id == user_id)
            .scalar_subquery()
        )
        condition = or_(
            Workspace.owner_id == user_id,
            Workspace.id.in_(member_subquery),
        )

        count_query = select(func.count(Workspace.id)).where(condition)
        total_result = await self.session.execute(count_query)
        total = total_result.scalar() or 0

        offset = (page - 1) * limit
        data_query = (
            select(Workspace)
            .where(condition)
            .order_by(Workspace.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(data_query)
        items = list(result.scalars().all())

        return PaginationResult(
            items=items,
            total=total,
            page=page,
            limit=limit,
            total_pages=math.ceil(total / limit) if limit > 0 else 0,
        )

    async def list_all_paginated(
        self,
        page: int = 1,
        limit: int = 20,
    ) -> PaginationResult[Workspace]:
        """Fetch all workspaces across the system for administrator audits."""
        return await self.get_all(page=page, limit=limit)
