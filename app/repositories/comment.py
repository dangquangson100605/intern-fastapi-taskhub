"""Comment repository handling comment persistence, author resolution, and single-join authorization."""

import math

from sqlalchemy import and_, func, select
from sqlalchemy.orm import selectinload

from app.models.comment import Comment
from app.models.enums import WorkspaceRole
from app.models.project import Project
from app.models.task import Task
from app.models.workspace import Workspace, WorkspaceMember
from app.repositories.base import BaseRepository, PaginationResult
from app.schemas.common import PaginationParams


class CommentRepository(BaseRepository[Comment]):
    """Repository managing Comment entity queries, author eager loading, and lifecycle."""

    model = Comment

    async def create_comment(
        self,
        task_id: int,
        author_id: int,
        content: str,
    ) -> Comment:
        """Insert and flush a new comment."""
        instance = self.model(
            task_id=task_id,
            author_id=author_id,
            content=content,
        )
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def list_by_task(
        self, task_id: int, pagination: PaginationParams
    ) -> PaginationResult[Comment]:
        """Fetch paginated comments belonging to a task ordered by created_at ascending."""
        count_query = select(func.count(Comment.id)).where(Comment.task_id == task_id)
        total_result = await self.session.execute(count_query)
        total = total_result.scalar() or 0

        query = (
            select(Comment)
            .where(Comment.task_id == task_id)
            .options(selectinload(Comment.author))
            .order_by(Comment.created_at.asc(), Comment.id.asc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
        result = await self.session.execute(query)
        items = list(result.scalars().all())

        return PaginationResult(
            items=items,
            total=total,
            page=pagination.page,
            limit=pagination.limit,
            total_pages=math.ceil(total / pagination.limit) if pagination.limit > 0 else 0,
        )

    async def get_with_task_and_workspace_role(
        self,
        comment_id: int,
        user_id: int,
    ) -> tuple[Comment, Task, Project, WorkspaceRole | None] | None:
        """Fetch comment with task, project, and caller workspace role in a single joined query."""
        query = (
            select(Comment, Task, Project, WorkspaceMember.role, Workspace.owner_id)
            .join(Task, Comment.task_id == Task.id)
            .join(Project, Task.project_id == Project.id)
            .join(Workspace, Project.workspace_id == Workspace.id)
            .outerjoin(
                WorkspaceMember,
                and_(
                    WorkspaceMember.workspace_id == Workspace.id,
                    WorkspaceMember.user_id == user_id,
                ),
            )
            .where(Comment.id == comment_id)
            .options(selectinload(Comment.author))
        )
        result = await self.session.execute(query)
        row = result.first()
        if row is None:
            return None

        comment, task, project, member_role, owner_id = row
        effective_role = WorkspaceRole.OWNER if owner_id == user_id else member_role
        return comment, task, project, effective_role
