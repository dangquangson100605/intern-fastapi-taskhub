"""Project repository handling database queries and access joins."""

import math

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ProjectStatus, WorkspaceRole
from app.models.project import Project
from app.models.workspace import Workspace, WorkspaceMember
from app.repositories.base import BaseRepository, PaginationResult
from app.schemas.common import PaginationParams


class ProjectRepository(BaseRepository[Project]):
    """Repository managing Project entity persistence."""

    model = Project

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_with_workspace_role(
        self,
        project_id: int,
        user_id: int,
    ) -> tuple[Project, WorkspaceRole | None] | None:
        """Fetch project and resolve user's role in the parent workspace in a single join query."""
        query = (
            select(Project, WorkspaceMember.role, Workspace.owner_id)
            .join(Workspace, Project.workspace_id == Workspace.id)
            .outerjoin(
                WorkspaceMember,
                and_(
                    WorkspaceMember.workspace_id == Workspace.id,
                    WorkspaceMember.user_id == user_id,
                ),
            )
            .where(Project.id == project_id)
        )
        result = await self.session.execute(query)
        row = result.first()
        if row is None:
            return None

        project, member_role, owner_id = row
        effective_role = WorkspaceRole.OWNER if owner_id == user_id else member_role
        return project, effective_role

    async def list_by_workspace(
        self,
        workspace_id: int,
        pagination: PaginationParams,
    ) -> PaginationResult[Project]:
        """Fetch paginated projects belonging to a workspace."""
        count_query = select(func.count(Project.id)).where(
            Project.workspace_id == workspace_id
        )
        total_result = await self.session.execute(count_query)
        total = total_result.scalar() or 0

        data_query = (
            select(Project)
            .where(Project.workspace_id == workspace_id)
            .order_by(Project.id.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
        result = await self.session.execute(data_query)
        items = list(result.scalars().all())

        return PaginationResult(
            items=items,
            total=total,
            page=pagination.page,
            limit=pagination.limit,
            total_pages=math.ceil(total / pagination.limit) if pagination.limit > 0 else 0,
        )

    async def create_project(
        self,
        workspace_id: int,
        name: str,
        description: str | None = None,
    ) -> Project:
        """Insert and flush a new project record."""
        return await self.create(
            workspace_id=workspace_id,
            name=name,
            description=description,
            status=ProjectStatus.ACTIVE,
        )

    async def update_status(
        self,
        project_id: int,
        status: ProjectStatus,
    ) -> Project | None:
        """Update lifecycle status of a project."""
        project = await self.get_by_id(project_id)
        if project is None:
            return None
        project.status = status
        await self.session.flush()
        await self.session.refresh(project)
        return project
