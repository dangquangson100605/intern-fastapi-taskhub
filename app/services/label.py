"""Label service managing label CRUD, scope validation, and task associations."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    RESOURCE_LABEL,
    RESOURCE_PROJECT,
    RESOURCE_TASK,
    RESOURCE_WORKSPACE,
    WORKSPACE_WRITE_ROLES,
)
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.core.messages import (
    ERROR_LABEL_ALREADY_ASSIGNED,
    ERROR_LABEL_NOT_ASSIGNED,
    ERROR_LABEL_PROJECT_MISMATCH,
    ERROR_PERMISSION_DENIED,
    ERROR_PROJECT_ARCHIVED,
    SUCCESS_LABEL_ASSIGNED,
    SUCCESS_LABEL_DELETED,
    SUCCESS_LABEL_REMOVED,
)
from app.models.enums import ProjectStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.repositories.label import LabelRepository
from app.repositories.project import ProjectRepository
from app.repositories.task import TaskRepository
from app.repositories.workspace import WorkspaceRepository
from app.repositories.workspace_member import WorkspaceMemberRepository
from app.schemas.common import MessageResponse
from app.schemas.label import LabelCreate, LabelResponse, LabelUpdate


class LabelService:
    """Service encapsulating label business logic, scope checks, and permissions."""

    def __init__(
        self,
        session: AsyncSession,
        label_repo: LabelRepository,
        project_repo: ProjectRepository,
        task_repo: TaskRepository,
        workspace_repo: WorkspaceRepository,
        member_repo: WorkspaceMemberRepository,
    ) -> None:
        self.session = session
        self.label_repo = label_repo
        self.project_repo = project_repo
        self.task_repo = task_repo
        self.workspace_repo = workspace_repo
        self.member_repo = member_repo

    async def _resolve_project_write_access(
        self,
        project_id: int,
        current_user: User,
    ) -> Project:
        """Verify project exists, user has write role in workspace, and project is active."""
        resolved = await self.project_repo.get_with_workspace_role(
            project_id=project_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException(RESOURCE_PROJECT, project_id)

        project, role = resolved
        is_admin = current_user.role == UserRole.ADMIN
        if not is_admin and role is None:
            raise NotFoundException(RESOURCE_PROJECT, project_id)

        if not is_admin and role not in WORKSPACE_WRITE_ROLES:
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        if project.status == ProjectStatus.ARCHIVED:
            raise ConflictException(ERROR_PROJECT_ARCHIVED)

        return project

    async def _resolve_task_write_access(
        self,
        task_id: int,
        current_user: User,
    ) -> tuple[Task, Project]:
        """Fetch task and verify caller write access and project active status."""
        resolved = await self.task_repo.get_with_project_and_workspace_role(
            task_id=task_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException(RESOURCE_TASK, task_id)

        task, project, role = resolved
        is_admin = current_user.role == UserRole.ADMIN
        if not is_admin and role is None:
            raise NotFoundException(RESOURCE_TASK, task_id)

        if not is_admin and role not in WORKSPACE_WRITE_ROLES:
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        if project.status == ProjectStatus.ARCHIVED:
            raise ConflictException(ERROR_PROJECT_ARCHIVED)

        return task, project

    async def create_label(
        self,
        project_id: int,
        current_user: User,
        data: LabelCreate,
    ) -> LabelResponse:
        """Create a new label inside a project enforcing workspace write permissions."""
        await self._resolve_project_write_access(project_id, current_user)
        label = await self.label_repo.create_label(
            project_id=project_id,
            name=data.name,
            color=data.color,
        )
        await self.session.commit()
        await self.session.refresh(label)
        return LabelResponse.model_validate(label)

    async def list_project_labels(
        self,
        project_id: int,
        current_user: User,
    ) -> list[LabelResponse]:
        """Retrieve all labels belonging to a project for any workspace member."""
        resolved = await self.project_repo.get_with_workspace_role(
            project_id=project_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException(RESOURCE_PROJECT, project_id)

        _, role = resolved
        if current_user.role != UserRole.ADMIN and role is None:
            raise NotFoundException(RESOURCE_PROJECT, project_id)

        labels = await self.label_repo.list_by_project(project_id)
        return [LabelResponse.model_validate(lbl) for lbl in labels]

    async def list_workspace_labels(
        self,
        workspace_id: int,
        current_user: User,
    ) -> list[LabelResponse]:
        """Retrieve all labels belonging to a workspace for any member."""
        ws = await self.workspace_repo.get_by_id(workspace_id)
        if ws is None:
            raise NotFoundException(RESOURCE_WORKSPACE, workspace_id)

        is_admin = current_user.role == UserRole.ADMIN
        if not is_admin:
            member = await self.member_repo.get_member(workspace_id, current_user.id)
            if member is None and ws.owner_id != current_user.id:
                raise NotFoundException(RESOURCE_WORKSPACE, workspace_id)

        labels = await self.label_repo.list_by_workspace(workspace_id)
        return [LabelResponse.model_validate(lbl) for lbl in labels]

    async def update_label(
        self,
        label_id: int,
        current_user: User,
        data: LabelUpdate,
    ) -> LabelResponse:
        """Update label attributes enforcing workspace write permissions."""
        resolved = await self.label_repo.get_with_project_and_workspace_role(
            label_id=label_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException(RESOURCE_LABEL, label_id)

        label, project, role = resolved
        is_admin = current_user.role == UserRole.ADMIN
        if not is_admin and role is None:
            raise NotFoundException(RESOURCE_LABEL, label_id)

        if not is_admin and role not in WORKSPACE_WRITE_ROLES:
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        if project.status == ProjectStatus.ARCHIVED:
            raise ConflictException(ERROR_PROJECT_ARCHIVED)

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(label, field, value)

        await self.session.commit()
        await self.session.refresh(label)
        return LabelResponse.model_validate(label)

    async def delete_label(
        self,
        label_id: int,
        current_user: User,
    ) -> MessageResponse:
        """Delete label enforcing write permissions and non-archived project status."""
        resolved = await self.label_repo.get_with_project_and_workspace_role(
            label_id=label_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException(RESOURCE_LABEL, label_id)

        label, project, role = resolved
        is_admin = current_user.role == UserRole.ADMIN
        if not is_admin and role is None:
            raise NotFoundException(RESOURCE_LABEL, label_id)

        if not is_admin and role not in WORKSPACE_WRITE_ROLES:
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        if project.status == ProjectStatus.ARCHIVED:
            raise ConflictException(ERROR_PROJECT_ARCHIVED)

        await self.label_repo.delete(label.id)
        await self.session.commit()
        return MessageResponse(message=SUCCESS_LABEL_DELETED)

    async def assign_label_to_task(
        self,
        task_id: int,
        label_id: int,
        current_user: User,
    ) -> MessageResponse:
        """Attach a label to a task checking same-project scope and duplicate prevention."""
        task, project = await self._resolve_task_write_access(task_id, current_user)

        label = await self.label_repo.get_by_id(label_id)
        if label is None:
            raise NotFoundException(RESOURCE_LABEL, label_id)

        if label.project_id != task.project_id:
            raise BadRequestException(ERROR_LABEL_PROJECT_MISMATCH)

        if await self.label_repo.is_assigned_to_task(task_id, label_id):
            raise ConflictException(ERROR_LABEL_ALREADY_ASSIGNED)

        await self.label_repo.assign_to_task(task_id, label_id)
        await self.session.commit()
        return MessageResponse(message=SUCCESS_LABEL_ASSIGNED)

    async def remove_label_from_task(
        self,
        task_id: int,
        label_id: int,
        current_user: User,
    ) -> MessageResponse:
        """Detach a label from a task enforcing write permissions."""
        task, project = await self._resolve_task_write_access(task_id, current_user)

        label = await self.label_repo.get_by_id(label_id)
        if label is None:
            raise NotFoundException(RESOURCE_LABEL, label_id)

        if not await self.label_repo.is_assigned_to_task(task_id, label_id):
            raise NotFoundException(message=ERROR_LABEL_NOT_ASSIGNED)

        await self.label_repo.remove_from_task(task_id, label_id)
        await self.session.commit()
        return MessageResponse(message=SUCCESS_LABEL_REMOVED)

    async def list_task_labels(
        self,
        task_id: int,
        current_user: User,
    ) -> list[LabelResponse]:
        """Fetch all labels attached to a task for any workspace member."""
        resolved = await self.task_repo.get_with_project_and_workspace_role(
            task_id=task_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException(RESOURCE_TASK, task_id)

        _, _, role = resolved
        if current_user.role != UserRole.ADMIN and role is None:
            raise NotFoundException(RESOURCE_TASK, task_id)

        labels = await self.label_repo.list_by_task(task_id)
        return [LabelResponse.model_validate(lbl) for lbl in labels]
