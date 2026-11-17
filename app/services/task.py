"""Task service orchestrating task management, RBAC, and assignee validation."""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

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
        """Ensure assignee is an active user and belongs to the specified workspace."""
        user = await self.user_repo.get_by_id(assignee_id)
        if user is None or not user.is_active:
            raise BadRequestException(ERROR_INACTIVE_USER)

        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if workspace is not None and workspace.owner_id == assignee_id:
            return

        member = await self.member_repo.get_member(workspace_id, assignee_id)
        if member is None:
            raise BadRequestException(ERROR_ASSIGNEE_NOT_IN_WORKSPACE)

    async def create_task(
        self,
        project_id: int,
        current_user: User,
        data: TaskCreate,
    ) -> TaskResponse:
        """Create a new task in a project verifying write role before checking archive status."""
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
            raise NotFoundException("Project")

        _, role = resolved
        if current_user.role != UserRole.ADMIN and role is None:
            raise NotFoundException("Project")

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
            raise NotFoundException("Task")

        task, _, role = resolved
        if current_user.role != UserRole.ADMIN and role is None:
            raise NotFoundException("Task")

        return TaskResponse.model_validate(task)

    async def update_task(
        self,
        task_id: int,
        current_user: User,
        data: TaskUpdate,
    ) -> TaskResponse:
        """Update task attributes enforcing write permissions and archive checks."""
        resolved = await self.task_repo.get_with_project_and_workspace_role(
            task_id=task_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException("Task")

        task, project, role = resolved
        is_admin = current_user.role == UserRole.ADMIN
        if not is_admin and role is None:
            raise NotFoundException("Task")

        if not is_admin and role == WorkspaceRole.VIEWER:
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        if project.status == ProjectStatus.ARCHIVED:
            raise ConflictException(ERROR_PROJECT_ARCHIVED)

        if data.assignee_id is not None:
            await self._validate_assignee_in_workspace(
                workspace_id=project.workspace_id,
                assignee_id=data.assignee_id,
            )

        if data.title is not None:
            task.title = data.title
        if data.description is not None:
            task.description = data.description
        if data.priority is not None:
            task.priority = data.priority
        if data.status is not None:
            task.status = data.status
        if data.assignee_id is not None:
            task.assignee_id = data.assignee_id
        if data.due_date is not None:
            task.due_date = data.due_date

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
        resolved = await self.task_repo.get_with_project_and_workspace_role(
            task_id=task_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException("Task")

        task, project, role = resolved
        is_admin = current_user.role == UserRole.ADMIN
        if not is_admin and role is None:
            raise NotFoundException("Task")

        if not is_admin and role == WorkspaceRole.VIEWER:
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        if project.status == ProjectStatus.ARCHIVED:
            raise ConflictException(ERROR_PROJECT_ARCHIVED)

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
        resolved = await self.task_repo.get_with_project_and_workspace_role(
            task_id=task_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException("Task")

        task, project, role = resolved
        is_admin = current_user.role == UserRole.ADMIN
        if not is_admin and role is None:
            raise NotFoundException("Task")

        if not is_admin and role == WorkspaceRole.VIEWER:
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        if project.status == ProjectStatus.ARCHIVED:
            raise ConflictException(ERROR_PROJECT_ARCHIVED)

        await self.task_repo.delete(task_id)
        await self.session.commit()
