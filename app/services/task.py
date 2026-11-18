"""Task service orchestrating task management, RBAC, and assignee validation."""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    RESOURCE_PROJECT,
    RESOURCE_TASK,
    RESOURCE_USER,
    WORKSPACE_WRITE_ROLES,
)
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.core.messages import (
    ERROR_ASSIGNEE_NOT_IN_WORKSPACE,
    ERROR_INACTIVE_USER,
    ERROR_PERMISSION_DENIED,
    ERROR_PROJECT_ARCHIVED,
)
from app.models.enums import ProjectStatus, TaskPriority, TaskStatus, UserRole, WorkspaceRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.repositories.project import ProjectRepository
from app.repositories.task import TaskRepository
from app.repositories.user import UserRepository
from app.repositories.workspace import WorkspaceRepository
from app.repositories.workspace_member import WorkspaceMemberRepository
from app.schemas.common import PaginatedResponse, PaginationParams
from app.schemas.task import TaskCreate, TaskResponse, TaskStatusUpdate, TaskUpdate


class TaskService:
    """Service managing task lifecycle, state transitions, and workspace validation."""

    def __init__(
        self,
        session: AsyncSession,
        task_repo: TaskRepository,
        project_repo: ProjectRepository,
        workspace_repo: WorkspaceRepository,
        member_repo: WorkspaceMemberRepository,
        user_repo: UserRepository,
    ) -> None:
        self.session = session
        self.task_repo = task_repo
        self.project_repo = project_repo
        self.workspace_repo = workspace_repo
        self.member_repo = member_repo
        self.user_repo = user_repo

    async def _validate_assignee_in_workspace(
        self,
        workspace_id: int,
        assignee_id: int,
    ) -> None:
        """Ensure assignee is an existing active member with write role in the specified workspace."""
        user = await self.user_repo.get_by_id(assignee_id)
        if user is None:
            raise NotFoundException(RESOURCE_USER, assignee_id)
        if not user.is_active:
            raise BadRequestException(ERROR_INACTIVE_USER)

        member = await self.member_repo.get_member(workspace_id, assignee_id)
        if member is None or member.role not in WORKSPACE_WRITE_ROLES:
            raise BadRequestException(ERROR_ASSIGNEE_NOT_IN_WORKSPACE)

    async def _get_project_for_create_task(
        self,
        project_id: int,
        current_user: User,
    ) -> Project:
        """Verify project exists, caller has write role, and project is active."""
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

        if not is_admin and role not in WORKSPACE_WRITE_ROLES:
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        if project.status == ProjectStatus.ARCHIVED:
            raise ConflictException(ERROR_PROJECT_ARCHIVED)

        return project

    async def _get_task_for_write(
        self,
        task_id: int,
        current_user: User,
        *,
        require_active_project: bool = True,
    ) -> tuple[Task, Project, WorkspaceRole | None]:
        """Fetch task and verify caller write access and project active status."""
        resolved = await self.task_repo.get_with_project_and_workspace_role(
            task_id=task_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException(RESOURCE_TASK)

        task, project, role = resolved
        is_admin = current_user.role == UserRole.ADMIN
        if not is_admin and role is None:
            raise NotFoundException(RESOURCE_TASK)

        if not is_admin and role not in WORKSPACE_WRITE_ROLES:
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        if require_active_project and project.status == ProjectStatus.ARCHIVED:
            raise ConflictException(ERROR_PROJECT_ARCHIVED)

        return task, project, role

    async def create_task(
        self,
        project_id: int,
        current_user: User,
        data: TaskCreate,
    ) -> TaskResponse:
        """Create a new task in a project verifying write role before checking archive status."""
        project = await self._get_project_for_create_task(
            project_id=project_id,
            current_user=current_user,
        )

        if data.assignee_id is not None:
            await self._validate_assignee_in_workspace(
                workspace_id=project.workspace_id,
                assignee_id=data.assignee_id,
            )

        task = await self.task_repo.create_task(
            project_id=project_id,
            created_by=current_user.id,
            title=data.title,
            description=data.description,
            priority=data.priority,
            assignee_id=data.assignee_id,
            due_date=data.due_date,
        )
        await self.session.commit()
        await self.session.refresh(task, attribute_names=["assignee", "creator"])
        return TaskResponse.model_validate(task)

    async def list_tasks(
        self,
        project_id: int,
        current_user: User,
        pagination: PaginationParams,
        statuses: Sequence[TaskStatus] | None = None,
        priorities: Sequence[TaskPriority] | None = None,
        assignee_id: int | None = None,
    ) -> PaginatedResponse[TaskResponse]:
        """List tasks within a project ensuring caller is a member."""
        resolved = await self.project_repo.get_with_workspace_role(
            project_id=project_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException(RESOURCE_PROJECT)

        _, role = resolved
        if current_user.role != UserRole.ADMIN and role is None:
            raise NotFoundException(RESOURCE_PROJECT)

        result = await self.task_repo.list_by_project(
            project_id=project_id,
            pagination=pagination,
            statuses=statuses,
            priorities=priorities,
            assignee_id=assignee_id,
        )
        return PaginatedResponse[TaskResponse](
            items=[TaskResponse.model_validate(t) for t in result.items],
            total=result.total,
            page=result.page,
            limit=result.limit,
            total_pages=result.total_pages,
        )

    async def get_task(
        self,
        task_id: int,
        current_user: User,
    ) -> TaskResponse:
        """Fetch task details verifying membership across task -> project -> workspace."""
        resolved = await self.task_repo.get_with_project_and_workspace_role(
            task_id=task_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException(RESOURCE_TASK)

        task, _, role = resolved
        if current_user.role != UserRole.ADMIN and role is None:
            raise NotFoundException(RESOURCE_TASK)

        return TaskResponse.model_validate(task)

    async def update_task(
        self,
        task_id: int,
        current_user: User,
        data: TaskUpdate,
    ) -> TaskResponse:
        """Update task attributes enforcing write permissions and allowing field unsetting."""
        task, project, _ = await self._get_task_for_write(
            task_id=task_id,
            current_user=current_user,
            require_active_project=True,
        )

        update_data = data.model_dump(exclude_unset=True)

        if "assignee_id" in update_data:
            new_assignee = update_data["assignee_id"]
            if new_assignee is not None:
                await self._validate_assignee_in_workspace(
                    workspace_id=project.workspace_id,
                    assignee_id=new_assignee,
                )

        for field, value in update_data.items():
            setattr(task, field, value)

        if "assignee_id" in update_data and update_data["assignee_id"] is None:
            task.assignee = None

        await self.session.commit()
        await self.session.refresh(task, attribute_names=["assignee", "creator"])
        return TaskResponse.model_validate(task)

    async def update_task_status(
        self,
        task_id: int,
        current_user: User,
        data: TaskStatusUpdate,
    ) -> TaskResponse:
        """Fast status transition enforcing write role before archive validation."""
        task, _, _ = await self._get_task_for_write(
            task_id=task_id,
            current_user=current_user,
            require_active_project=True,
        )

        task.status = data.status
        await self.session.commit()
        await self.session.refresh(task, attribute_names=["assignee", "creator"])
        return TaskResponse.model_validate(task)

    async def delete_task(
        self,
        task_id: int,
        current_user: User,
    ) -> None:
        """Delete task verifying write role and non-archived project status."""
        await self._get_task_for_write(
            task_id=task_id,
            current_user=current_user,
            require_active_project=True,
        )

        await self.task_repo.delete(task_id)
        await self.session.commit()
