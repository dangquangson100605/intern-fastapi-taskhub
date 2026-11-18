"""Project service managing project CRUD, permissions, and archive status."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    RESOURCE_PROJECT,
    RESOURCE_WORKSPACE,
    WORKSPACE_WRITE_ROLES,
)
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
from app.models.project import Project
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
        """Resolve caller's role in workspace, checking workspace existence first."""
        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if workspace is None:
            return None

        if current_user.role == UserRole.ADMIN:
            return WorkspaceRole.OWNER

        if workspace.owner_id == current_user.id:
            return WorkspaceRole.OWNER

        member = await self.member_repo.get_member(workspace_id, current_user.id)
        return member.role if member is not None else None

    async def _get_project_for_write(
        self,
        project_id: int,
        current_user: User,
        *,
        require_active: bool = True,
        owner_only: bool = False,
    ) -> tuple[Project, WorkspaceRole | None]:
        """Fetch project and verify caller has write privileges in parent workspace."""
        resolved = await self.project_repo.get_with_workspace_role(
            project_id=project_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException(RESOURCE_PROJECT)

        project, role = resolved
        is_admin = current_user.role == UserRole.ADMIN
        if not is_admin and role is None:
            raise NotFoundException(RESOURCE_PROJECT)

        if not is_admin:
            if owner_only and role != WorkspaceRole.OWNER:
                raise ForbiddenException(ERROR_PERMISSION_DENIED)
            if role not in WORKSPACE_WRITE_ROLES:
                raise ForbiddenException(ERROR_PERMISSION_DENIED)

        if require_active and project.status == ProjectStatus.ARCHIVED:
            raise ConflictException(ERROR_PROJECT_ARCHIVED)

        return project, role

    async def create_project(
        self,
        workspace_id: int,
        current_user: User,
        data: ProjectCreate,
    ) -> ProjectResponse:
        """Create a new project requiring EDITOR or OWNER role in the target workspace."""
        role = await self._resolve_workspace_access(workspace_id, current_user)
        if role is None:
            raise NotFoundException(RESOURCE_WORKSPACE)
        if current_user.role != UserRole.ADMIN and role not in WORKSPACE_WRITE_ROLES:
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
            raise NotFoundException(RESOURCE_WORKSPACE)

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
            raise NotFoundException(RESOURCE_PROJECT)

        project, role = resolved
        if current_user.role != UserRole.ADMIN and role is None:
            raise NotFoundException(RESOURCE_PROJECT)

        return ProjectResponse.model_validate(project)

    async def update_project(
        self,
        project_id: int,
        current_user: User,
        data: ProjectUpdate,
    ) -> ProjectResponse:
        """Update project verifying write role before checking archive status."""
        project, _ = await self._get_project_for_write(
            project_id=project_id,
            current_user=current_user,
            require_active=True,
        )

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(project, field, value)

        await self.session.commit()
        await self.session.refresh(project)
        return ProjectResponse.model_validate(project)

    async def archive_project(
        self,
        project_id: int,
        current_user: User,
    ) -> ProjectResponse:
        """Archive project verifying owner permissions first."""
        project, _ = await self._get_project_for_write(
            project_id=project_id,
            current_user=current_user,
            require_active=False,
            owner_only=True,
        )

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
        project, _ = await self._get_project_for_write(
            project_id=project_id,
            current_user=current_user,
            require_active=False,
            owner_only=True,
        )

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
        """Delete project cascade deleting tasks, requiring active status and owner privileges."""
        await self._get_project_for_write(
            project_id=project_id,
            current_user=current_user,
            require_active=True,
            owner_only=True,
        )

        await self.project_repo.delete(project_id)
        await self.session.commit()
