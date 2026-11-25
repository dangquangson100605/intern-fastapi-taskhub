"""Task service orchestrating task management, RBAC, filtering, and cache invalidation."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheService
from app.core.config import get_settings
from app.core.constants import (
    RESOURCE_PROJECT,
    RESOURCE_TASK,
    RESOURCE_USER,
    WORKSPACE_WRITE_ROLES,
)
from app.core.datetime_utils import to_utc_naive
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.core.messages import (
    ERROR_ASSIGNEE_NOT_IN_WORKSPACE,
    ERROR_INACTIVE_USER,
    ERROR_INVALID_DATE_RANGE,
    ERROR_PERMISSION_DENIED,
    ERROR_PROJECT_ARCHIVED,
)
from app.models.enums import (
    ProjectStatus,
    SortOrder,
    TaskPriority,
    TaskSortBy,
    TaskStatus,
    UserRole,
    WorkspaceRole,
)
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
from app.services.notification import NotificationService


class TaskService:
    """Service managing task lifecycle, state transitions, caching, and workspace validation."""

    def __init__(
        self,
        session: AsyncSession,
        task_repo: TaskRepository,
        project_repo: ProjectRepository,
        workspace_repo: WorkspaceRepository,
        member_repo: WorkspaceMemberRepository,
        user_repo: UserRepository,
        cache_service: CacheService,
        notification_service: NotificationService | None = None,
    ) -> None:
        self.session = session
        self.task_repo = task_repo
        self.project_repo = project_repo
        self.workspace_repo = workspace_repo
        self.member_repo = member_repo
        self.user_repo = user_repo
        self.cache_service = cache_service
        self.notification_service = notification_service or NotificationService()

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
        background_tasks: BackgroundTasks | None = None,
    ) -> TaskResponse:
        """Create a new task in a project verifying write role and invalidating project cache."""
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
        await self.session.refresh(task)
        await self.session.refresh(task, attribute_names=["creator", "assignee"])
        await self.cache_service.bump_project_tasks_version(project_id)

        assignee_user = task.assignee
        if assignee_user is None and task.assignee_id is not None:
            assignee_user = await self.user_repo.get_by_id(task.assignee_id)

        if background_tasks is not None and assignee_user is not None:
            background_tasks.add_task(
                self.notification_service.send_task_assignment_notification,
                assignee_email=assignee_user.email,
                assignee_name=assignee_user.full_name,
                task_title=task.title,
                project_name=project.name,
                assigner_name=current_user.full_name,
            )

        return TaskResponse.model_validate(task)

    def _serialize_query_parts(
        self,
        search: str | None,
        statuses: Sequence[TaskStatus] | None,
        priorities: Sequence[TaskPriority] | None,
        assignee_id: int | None,
        due_date_from: datetime | None,
        due_date_to: datetime | None,
        label_id: int | None,
        sort_by: TaskSortBy,
        sort_order: SortOrder,
    ) -> dict[str, Any]:
        """Serialize query parameters for deterministic hashing."""
        return {
            "search": search or "",
            "statuses": sorted([s.value for s in statuses]) if statuses else [],
            "priorities": sorted([p.value for p in priorities]) if priorities else [],
            "assignee_id": assignee_id,
            "due_date_from": due_date_from.isoformat() if due_date_from else None,
            "due_date_to": due_date_to.isoformat() if due_date_to else None,
            "label_id": label_id,
            "sort_by": sort_by.value,
            "sort_order": sort_order.value,
        }

    async def _get_cached_tasks(
        self,
        project_id: int,
        version: int,
        pagination: PaginationParams,
        query_parts: dict[str, Any],
    ) -> PaginatedResponse[TaskResponse] | None:
        """Fetch and deserialize cached tasks page if present."""
        cache_key = self.cache_service.build_project_tasks_cache_key(
            project_id=project_id,
            version=version,
            page=pagination.page,
            limit=pagination.limit,
            query_parts=query_parts,
        )
        cached_data = await self.cache_service.get(cache_key)
        if cached_data is not None:
            return PaginatedResponse[TaskResponse].model_validate(cached_data)
        return None

    async def _set_cached_tasks(
        self,
        project_id: int,
        version: int,
        pagination: PaginationParams,
        query_parts: dict[str, Any],
        response: PaginatedResponse[TaskResponse],
    ) -> None:
        """Write paginated tasks response to Redis cache."""
        cache_key = self.cache_service.build_project_tasks_cache_key(
            project_id=project_id,
            version=version,
            page=pagination.page,
            limit=pagination.limit,
            query_parts=query_parts,
        )
        await self.cache_service.set(
            cache_key,
            response.model_dump(mode="json"),
            ttl=get_settings().TASK_CACHE_TTL_SECONDS,
        )

    async def list_tasks(
        self,
        project_id: int,
        current_user: User,
        pagination: PaginationParams,
        search: str | None = None,
        statuses: Sequence[TaskStatus] | None = None,
        priorities: Sequence[TaskPriority] | None = None,
        assignee_id: int | None = None,
        due_date_from: datetime | None = None,
        due_date_to: datetime | None = None,
        label_id: int | None = None,
        sort_by: TaskSortBy = TaskSortBy.CREATED_AT,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> PaginatedResponse[TaskResponse]:
        """List tasks with dynamic filters, sorting, and versioned Redis caching."""
        resolved = await self.project_repo.get_with_workspace_role(
            project_id=project_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException(RESOURCE_PROJECT)

        _, role = resolved
        if current_user.role != UserRole.ADMIN and role is None:
            raise NotFoundException(RESOURCE_PROJECT)

        norm_due_from = to_utc_naive(due_date_from)
        norm_due_to = to_utc_naive(due_date_to)
        if norm_due_from is not None and norm_due_to is not None and norm_due_from > norm_due_to:
            raise BadRequestException(ERROR_INVALID_DATE_RANGE)

        clean_search = search.strip() if search and search.strip() else None

        version = await self.cache_service.get_project_tasks_version(project_id)
        query_parts = self._serialize_query_parts(
            search=clean_search,
            statuses=statuses,
            priorities=priorities,
            assignee_id=assignee_id,
            due_date_from=norm_due_from,
            due_date_to=norm_due_to,
            label_id=label_id,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        cached_response = await self._get_cached_tasks(
            project_id=project_id,
            version=version,
            pagination=pagination,
            query_parts=query_parts,
        )
        if cached_response is not None:
            return cached_response

        result = await self.task_repo.list_by_project(
            project_id=project_id,
            pagination=pagination,
            search=clean_search,
            statuses=statuses,
            priorities=priorities,
            assignee_id=assignee_id,
            due_date_from=norm_due_from,
            due_date_to=norm_due_to,
            label_id=label_id,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        response = PaginatedResponse[TaskResponse](
            items=[TaskResponse.model_validate(t) for t in result.items],
            total=result.total,
            page=result.page,
            limit=result.limit,
            total_pages=result.total_pages,
        )
        await self._set_cached_tasks(
            project_id=project_id,
            version=version,
            pagination=pagination,
            query_parts=query_parts,
            response=response,
        )
        return response

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
        background_tasks: BackgroundTasks | None = None,
    ) -> TaskResponse:
        """Update task attributes and invalidate project task caches."""
        task, project, _ = await self._get_task_for_write(
            task_id=task_id,
            current_user=current_user,
            require_active_project=True,
        )

        old_assignee_id = task.assignee_id
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
        await self.session.refresh(task)
        await self.session.refresh(task, attribute_names=["creator", "assignee"])
        await self.cache_service.bump_project_tasks_version(project.id)

        assignee_user = task.assignee
        if assignee_user is None and task.assignee_id is not None:
            assignee_user = await self.user_repo.get_by_id(task.assignee_id)

        if (
            background_tasks is not None
            and assignee_user is not None
            and task.assignee_id != old_assignee_id
        ):
            background_tasks.add_task(
                self.notification_service.send_task_assignment_notification,
                assignee_email=assignee_user.email,
                assignee_name=assignee_user.full_name,
                task_title=task.title,
                project_name=project.name,
                assigner_name=current_user.full_name,
            )

        return TaskResponse.model_validate(task)

    async def update_task_status(
        self,
        task_id: int,
        current_user: User,
        data: TaskStatusUpdate,
        background_tasks: BackgroundTasks | None = None,
    ) -> TaskResponse:
        """Fast status transition and cache invalidation."""
        task, project, _ = await self._get_task_for_write(
            task_id=task_id,
            current_user=current_user,
            require_active_project=True,
        )

        old_status = task.status
        task.status = data.status
        await self.session.commit()
        await self.session.refresh(task)
        await self.session.refresh(task, attribute_names=["creator", "assignee"])
        await self.cache_service.bump_project_tasks_version(task.project_id)

        if background_tasks is not None and old_status != data.status:
            recipients: list[str] = []
            creator_user = task.creator or await self.user_repo.get_by_id(task.created_by)
            if creator_user and creator_user.email:
                recipients.append(creator_user.email)

            assignee_user = task.assignee
            if assignee_user is None and task.assignee_id is not None:
                assignee_user = await self.user_repo.get_by_id(task.assignee_id)

            if assignee_user and assignee_user.email and assignee_user.email not in recipients:
                recipients.append(assignee_user.email)

            if recipients:
                background_tasks.add_task(
                    self.notification_service.send_task_status_changed_notification,
                    recipient_emails=recipients,
                    task_title=task.title,
                    project_name=project.name,
                    old_status=old_status,
                    new_status=data.status,
                    updater_name=current_user.full_name,
                )

        return TaskResponse.model_validate(task)

    async def delete_task(
        self,
        task_id: int,
        current_user: User,
    ) -> None:
        """Delete task verifying write role and invalidating project cache."""
        task, project, _ = await self._get_task_for_write(
            task_id=task_id,
            current_user=current_user,
            require_active_project=True,
        )
        project_id = project.id

        await self.task_repo.delete(task_id)
        await self.session.commit()
        await self.cache_service.bump_project_tasks_version(project_id)
