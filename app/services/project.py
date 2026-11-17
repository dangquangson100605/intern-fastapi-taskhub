"""Project service managing project CRUD, permissions, and archive status."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.core.messages import (
    ERROR_PERMISSION_DENIED,
    ERROR_PROJECT_ALREADY_ACTIVE,
    ERROR_PROJECT_ALREADY_ARCHIVED,
    ERROR_PROJECT_ARCHIVED,
)
from app.models.enums import ProjectStatus, UserRole, WorkspaceRole
from app.models.user import User
from app.repositories.project import ProjectRepository
from app.repositories.workspace import WorkspaceRepository
from app.repositories.workspace_member import WorkspaceMemberRepository
from app.schemas.common import PaginatedResponse, PaginationParams
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate


class ProjectService:
    """Service encapsulating project domain logic and workspace role enforcement."""

    def __init__(
        self,
        session: AsyncSession,
        project_repo: ProjectRepository,
        workspace_repo: WorkspaceRepository,
        member_repo: WorkspaceMemberRepository,
    ) -> None:
        self.session = session
        self.project_repo = project_repo
        self.workspace_repo = workspace_repo
        self.member_repo = member_repo

    async def _resolve_workspace_access(
        self,
        workspace_id: int,
        current_user: User,
    ) -> WorkspaceRole | None:
        """Resolve caller's role in workspace, returning None for outsiders."""
        if current_user.role == UserRole.ADMIN:
            return WorkspaceRole.OWNER

        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if workspace is None:
            return None

        if workspace.owner_id == current_user.id:
            return WorkspaceRole.OWNER

        member = await self.member_repo.get_member(workspace_id, current_user.id)
        return member.role if member is not None else None

    async def create_project(
        self,
        workspace_id: int,
        current_user: User,
        data: ProjectCreate,
    ) -> ProjectResponse:
        """Create a new project requiring EDITOR or OWNER role in the target workspace."""
        role = await self._resolve_workspace_access(workspace_id, current_user)
        if role is None:
            raise NotFoundException("Workspace")
        if role == WorkspaceRole.VIEWER:
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        project = await self.project_repo.create_project(
            workspace_id=workspace_id,
            name=data.name,
            description=data.description,
        )
        await self.session.commit()
        await self.session.refresh(project)
        return ProjectResponse.model_validate(project)

    async def list_projects(
        self,
        workspace_id: int,
        current_user: User,
        pagination: PaginationParams,
    ) -> PaginatedResponse[ProjectResponse]:
        """List paginated projects for any workspace member."""
        role = await self._resolve_workspace_access(workspace_id, current_user)
        if role is None:
            raise NotFoundException("Workspace")

        result = await self.project_repo.list_by_workspace(
            workspace_id=workspace_id,
            pagination=pagination,
        )
        return PaginatedResponse[ProjectResponse](
            items=[ProjectResponse.model_validate(p) for p in result.items],
            total=result.total,
            page=result.page,
            limit=result.limit,
            total_pages=result.total_pages,
        )

    async def get_project(
        self,
        project_id: int,
        current_user: User,
    ) -> ProjectResponse:
        """Fetch project ensuring caller has membership in the parent workspace."""
        resolved = await self.project_repo.get_with_workspace_role(
            project_id=project_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException("Project")

        project, role = resolved
        if current_user.role != UserRole.ADMIN and role is None:
            raise NotFoundException("Project")

        return ProjectResponse.model_validate(project)

    async def update_project(
        self,
        project_id: int,
        current_user: User,
        data: ProjectUpdate,
    ) -> ProjectResponse:
        """Update project verifying write role before checking archive status."""
        resolved = await self.project_repo.get_with_workspace_role(
            project_id=project_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException("Project")

        project, role = resolved
        is_admin = current_user.role == UserRole.ADMIN
        if not is_admin and role is None:
            raise NotFoundException("Project")

        if not is_admin and role == WorkspaceRole.VIEWER:
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        if project.status == ProjectStatus.ARCHIVED:
            raise ConflictException(ERROR_PROJECT_ARCHIVED)

        if data.name is not None:
            project.name = data.name
        if data.description is not None:
            project.description = data.description

        await self.session.commit()
        await self.session.refresh(project)
        return ProjectResponse.model_validate(project)

    async def archive_project(
        self,
        project_id: int,
        current_user: User,
    ) -> ProjectResponse:
        """Archive project checking write permissions first."""
        resolved = await self.project_repo.get_with_workspace_role(
            project_id=project_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException("Project")

        project, role = resolved
        is_admin = current_user.role == UserRole.ADMIN
        if not is_admin and role is None:
            raise NotFoundException("Project")

        if not is_admin and role == WorkspaceRole.VIEWER:
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        if project.status == ProjectStatus.ARCHIVED:
            raise ConflictException(ERROR_PROJECT_ALREADY_ARCHIVED)

        project.status = ProjectStatus.ARCHIVED
        await self.session.commit()
        await self.session.refresh(project)
        return ProjectResponse.model_validate(project)

    async def unarchive_project(
        self,
        project_id: int,
        current_user: User,
    ) -> ProjectResponse:
        """Unarchive an archived project restoring active status."""
        resolved = await self.project_repo.get_with_workspace_role(
            project_id=project_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException("Project")

        project, role = resolved
        is_admin = current_user.role == UserRole.ADMIN
        if not is_admin and role is None:
            raise NotFoundException("Project")

        if not is_admin and role == WorkspaceRole.VIEWER:
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        if project.status == ProjectStatus.ACTIVE:
            raise ConflictException(ERROR_PROJECT_ALREADY_ACTIVE)

        project.status = ProjectStatus.ACTIVE
        await self.session.commit()
        await self.session.refresh(project)
        return ProjectResponse.model_validate(project)

    async def delete_project(
        self,
        project_id: int,
        current_user: User,
    ) -> None:
        """Delete project cascade deleting tasks."""
        resolved = await self.project_repo.get_with_workspace_role(
            project_id=project_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException("Project")

        project, role = resolved
        is_admin = current_user.role == UserRole.ADMIN
        if not is_admin and role is None:
            raise NotFoundException("Project")

        if not is_admin and role == WorkspaceRole.VIEWER:
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        await self.project_repo.delete(project_id)
        await self.session.commit()
