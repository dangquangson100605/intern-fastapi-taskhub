"""WorkspaceMember repository managing membership records and roles."""

import math
from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import WorkspaceRole
from app.models.workspace import WorkspaceMember
from app.repositories.base import BaseRepository, PaginationResult


class WorkspaceMemberRepository(BaseRepository[WorkspaceMember]):
    """Repository managing WorkspaceMember entity persistence."""

    model = WorkspaceMember

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_member(
        self,
        workspace_id: int,
        user_id: int,
    ) -> WorkspaceMember | None:
        """Fetch a specific member record within a workspace, including user info."""
        query = (
            select(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
            .options(selectinload(WorkspaceMember.user))
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_members(
        self,
        workspace_id: int,
        page: int = 1,
        limit: int = 20,
    ) -> PaginationResult[WorkspaceMember]:
        """Fetch paginated member records belonging to a workspace."""
        count_query = select(func.count(WorkspaceMember.id)).where(
            WorkspaceMember.workspace_id == workspace_id
        )
        total_result = await self.session.execute(count_query)
        total = total_result.scalar() or 0

        offset = (page - 1) * limit
        data_query = (
            select(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .options(selectinload(WorkspaceMember.user))
            .order_by(WorkspaceMember.id.asc())
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

    async def add_member(
        self,
        workspace_id: int,
        user_id: int,
        role: WorkspaceRole = WorkspaceRole.VIEWER,
    ) -> WorkspaceMember:
        """Insert a new workspace member record and load its user relationship."""
        member = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=user_id,
            role=role,
        )
        self.session.add(member)
        await self.session.flush()
        return await self.get_member(workspace_id, user_id) or member

    async def update_role(
        self,
        workspace_id: int,
        user_id: int,
        role: WorkspaceRole,
    ) -> WorkspaceMember | None:
        """Update a member's role within a workspace."""
        member = await self.get_member(workspace_id, user_id)
        if member is None:
            return None
        member.role = role
        await self.session.flush()
        await self.session.refresh(member)
        return member

    async def remove_member(
        self,
        workspace_id: int,
        user_id: int,
    ) -> bool:
        """Remove a member from a workspace; returns True if deleted."""
        stmt = delete(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        await self.session.flush()
        return (result.rowcount or 0) > 0

    async def get_roles_by_workspace_ids(
        self,
        workspace_ids: Sequence[int],
        user_id: int,
    ) -> dict[int, WorkspaceRole]:
        """Batch-fetch member roles for given workspaces in a single query."""
        if not workspace_ids:
            return {}
        query = select(WorkspaceMember.workspace_id, WorkspaceMember.role).where(
            WorkspaceMember.workspace_id.in_(workspace_ids),
            WorkspaceMember.user_id == user_id,
        )
        result = await self.session.execute(query)
        return {ws_id: role for ws_id, role in result.all()}
