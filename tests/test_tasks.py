"""Unit, RBAC, and business logic tests for Projects and Tasks."""

import math
from collections.abc import Generator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.cache import CacheService
from app.core.config import get_settings
from app.core.dependencies import (
    get_cache_service,
    get_current_user,
    get_db,
    get_project_repository,
    get_project_service,
    get_task_repository,
    get_task_service,
    get_user_repository,
    get_workspace_member_repository,
    get_workspace_repository,
)
from app.core.messages import (
    ERROR_ASSIGNEE_NOT_IN_WORKSPACE,
    ERROR_DUE_DATE_IN_PAST,
    ERROR_PERMISSION_DENIED,
    ERROR_PROJECT_ALREADY_ACTIVE,
    ERROR_PROJECT_ALREADY_ARCHIVED,
    ERROR_PROJECT_ARCHIVED,
)
from app.main import app
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
from app.models.workspace import Workspace
from app.repositories.base import PaginationResult
from app.repositories.project import ProjectRepository
from app.repositories.task import TaskRepository
from app.schemas.common import PaginationParams
from app.services.notification import NotificationService
from app.services.project import ProjectService
from app.services.task import TaskService
from tests.conftest import (
    FakeAsyncSession,
    FakeRedis,
    InMemoryUserRepository,
    InMemoryWorkspaceMemberRepository,
    InMemoryWorkspaceRepository,
)


class InMemoryProjectRepository(ProjectRepository):
    """In-memory project repository with joined workspace role lookup."""

    def __init__(
        self,
        session: AsyncSession,
        workspace_repo: InMemoryWorkspaceRepository,
        member_repo: InMemoryWorkspaceMemberRepository,
    ) -> None:
        super().__init__(session)
        self.workspace_repo = workspace_repo
        self.member_repo = member_repo
        self._projects: dict[int, Project] = {}
        self._next_id: int = 1

    async def create(self, **kwargs: Any) -> Project:
        p = Project(
            id=self._next_id,
            workspace_id=int(kwargs["workspace_id"]),
            name=str(kwargs["name"]),
            description=kwargs.get("description"),
            status=kwargs.get("status", ProjectStatus.ACTIVE),
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self._projects[self._next_id] = p
        self._next_id += 1
        return p

    async def get_by_id(self, record_id: int) -> Project | None:
        return self._projects.get(record_id)

    async def get_with_workspace_role(
        self, project_id: int, user_id: int
    ) -> tuple[Project, WorkspaceRole | None] | None:
        project = self._projects.get(project_id)
        if project is None:
            return None
        ws = self.workspace_repo._workspaces.get(project.workspace_id)
        if ws is None:
            return None
        if ws.owner_id == user_id:
            return project, WorkspaceRole.OWNER
        member = self.member_repo._members.get((ws.id, user_id))
        return project, (member.role if member is not None else None)

    async def list_by_workspace(
        self, workspace_id: int, pagination: PaginationParams
    ) -> PaginationResult[Project]:
        matched = [p for p in self._projects.values() if p.workspace_id == workspace_id]
        total = len(matched)
        offset = pagination.offset
        items = matched[offset : offset + pagination.limit]
        return PaginationResult(
            items=items,
            total=total,
            page=pagination.page,
            limit=pagination.limit,
            total_pages=math.ceil(total / pagination.limit) if pagination.limit > 0 else 0,
        )

    async def delete(self, record_id: int) -> bool:
        if record_id in self._projects:
            del self._projects[record_id]
            return True
        return False


class InMemoryTaskRepository(TaskRepository):
    """In-memory task repository with filtering and pagination."""

    def __init__(
        self,
        session: AsyncSession,
        project_repo: InMemoryProjectRepository,
        user_repo: InMemoryUserRepository,
    ) -> None:
        super().__init__(session)
        self.project_repo = project_repo
        self.user_repo = user_repo
        self._tasks: dict[int, Task] = {}
        self._next_id: int = 1
        if hasattr(session, "refresh_callbacks"):
            session.refresh_callbacks.append(self._on_session_refresh)

    def _on_session_refresh(self, instance: Any, attribute_names: Sequence[str] | None) -> None:
        if isinstance(instance, Task):
            self._attach_relations(instance)

    def _attach_relations(self, task: Task) -> Task:
        task.creator = self.user_repo._users.get(task.created_by)  # type: ignore[assignment]
        if task.assignee_id is not None:
            task.assignee = self.user_repo._users.get(task.assignee_id)  # type: ignore[assignment]
        else:
            task.assignee = None
        return task

    async def create_task(
        self,
        project_id: int,
        created_by: int,
        title: str,
        description: str | None = None,
        priority: TaskPriority = TaskPriority.MEDIUM,
        assignee_id: int | None = None,
        due_date: datetime | None = None,
    ) -> Task:
        t = Task(
            id=self._next_id,
            project_id=project_id,
            created_by=created_by,
            title=title,
            description=description,
            status=TaskStatus.TODO,
            priority=priority,
            assignee_id=assignee_id,
            due_date=due_date,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self._tasks[self._next_id] = t
        self._next_id += 1
        return self._attach_relations(t)

    async def get_by_id(self, record_id: int) -> Task | None:
        task = self._tasks.get(record_id)
        if task is None:
            return None
        return self._attach_relations(task)

    async def get_with_project_and_workspace_role(
        self, task_id: int, user_id: int
    ) -> tuple[Task, Project, WorkspaceRole | None] | None:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        res = await self.project_repo.get_with_workspace_role(task.project_id, user_id)
        if res is None:
            return None
        project, role = res
        return self._attach_relations(task), project, role

    async def list_by_project(
        self,
        project_id: int,
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
    ) -> PaginationResult[Task]:
        matched = [t for t in self._tasks.values() if t.project_id == project_id]
        if search:
            kw = search.lower()
            matched = [
                t for t in matched
                if (t.title and kw in t.title.lower()) or (t.description and kw in t.description.lower())
            ]
        if statuses:
            matched = [t for t in matched if t.status in statuses]
        if priorities:
            matched = [t for t in matched if t.priority in priorities]
        if assignee_id is not None:
            matched = [t for t in matched if t.assignee_id == assignee_id]
        if due_date_from is not None:
            matched = [t for t in matched if t.due_date is not None and t.due_date >= due_date_from]
        if due_date_to is not None:
            matched = [t for t in matched if t.due_date is not None and t.due_date <= due_date_to]

        if label_id is not None:
            matched = [
                t
                for t in matched
                if any(getattr(lbl, "id", None) == label_id for lbl in getattr(t, "labels", []))
            ]

        total = len(matched)
        if sort_by == TaskSortBy.PRIORITY:
            prio_order = {
                TaskPriority.LOW: 1,
                TaskPriority.MEDIUM: 2,
                TaskPriority.HIGH: 3,
                TaskPriority.URGENT: 4,
            }
            matched.sort(
                key=lambda t: (prio_order.get(t.priority, 0), t.id),
                reverse=sort_order == SortOrder.DESC,
            )
        elif sort_by == TaskSortBy.DUE_DATE:
            matched.sort(
                key=lambda t: (
                    t.due_date is None,
                    (
                        t.due_date
                        if sort_order == SortOrder.ASC
                        else -(t.due_date.timestamp() if t.due_date else 0)
                    ),
                    t.id if sort_order == SortOrder.ASC else -t.id,
                ),
            )
        elif sort_by == TaskSortBy.TITLE:
            matched.sort(
                key=lambda t: (t.title.lower(), t.id),
                reverse=sort_order == SortOrder.DESC,
            )
        else:
            matched.sort(
                key=lambda t: (t.created_at, t.id),
                reverse=sort_order == SortOrder.DESC,
            )
        offset = pagination.offset
        items = [self._attach_relations(t) for t in matched[offset : offset + pagination.limit]]
        return PaginationResult(
            items=items,
            total=total,
            page=pagination.page,
            limit=pagination.limit,
            total_pages=math.ceil(total / pagination.limit) if pagination.limit > 0 else 0,
        )

    async def delete(self, record_id: int) -> bool:
        if record_id in self._tasks:
            del self._tasks[record_id]
            return True
        return False


class TaskTestContext:
    """Encapsulates test repositories, services, and actor accounts."""

    def __init__(self) -> None:
        self.session = cast(AsyncSession, FakeAsyncSession())
        self.fake_redis = FakeRedis()
        self.cache_service = CacheService(cast(Redis, self.fake_redis))
        self.user_repo = InMemoryUserRepository(self.session)
        self.member_repo = InMemoryWorkspaceMemberRepository(self.session, self.user_repo)
        self.workspace_repo = InMemoryWorkspaceRepository(self.session, self.member_repo)
        self.project_repo = InMemoryProjectRepository(
            self.session, self.workspace_repo, self.member_repo
        )
        self.task_repo = InMemoryTaskRepository(self.session, self.project_repo, self.user_repo)

        self.project_service = ProjectService(
            session=self.session,
            project_repo=self.project_repo,
            workspace_repo=self.workspace_repo,
            member_repo=self.member_repo,
        )
        self.notification_service = NotificationService()
        self.task_service = TaskService(
            session=self.session,
            task_repo=self.task_repo,
            project_repo=self.project_repo,
            workspace_repo=self.workspace_repo,
            member_repo=self.member_repo,
            user_repo=self.user_repo,
            cache_service=self.cache_service,
            notification_service=self.notification_service,
        )

        self.owner = self.user_repo.add_test_user(1, "owner@example.com")
        self.editor = self.user_repo.add_test_user(2, "editor@example.com")
        self.viewer = self.user_repo.add_test_user(3, "viewer@example.com")
        self.outsider = self.user_repo.add_test_user(4, "outsider@example.com")
        self.admin = self.user_repo.add_test_user(5, "admin@example.com", role=UserRole.ADMIN)


@pytest.fixture
def task_ctx() -> Generator[TaskTestContext, None, None]:
    """Wire in-memory test repositories into dependency overrides."""
    ctx = TaskTestContext()
    app.dependency_overrides[get_db] = lambda: ctx.session
    app.dependency_overrides[get_cache_service] = lambda: ctx.cache_service
    app.dependency_overrides[get_user_repository] = lambda: ctx.user_repo
    app.dependency_overrides[get_workspace_repository] = lambda: ctx.workspace_repo
    app.dependency_overrides[get_workspace_member_repository] = lambda: ctx.member_repo
    app.dependency_overrides[get_project_repository] = lambda: ctx.project_repo
    app.dependency_overrides[get_task_repository] = lambda: ctx.task_repo
    app.dependency_overrides[get_project_service] = lambda: ctx.project_service
    app.dependency_overrides[get_task_service] = lambda: ctx.task_service
    yield ctx
    app.dependency_overrides.clear()


async def _seed_workspace_and_project(
    ctx: TaskTestContext,
) -> tuple[Workspace, Project]:
    """Helper creating a workspace with owner, editor, viewer, and an active project."""
    ws = await ctx.workspace_repo.create(name="Engineering Workspace", owner_id=ctx.owner.id)
    await ctx.member_repo.add_member(ws.id, ctx.owner.id, role=WorkspaceRole.OWNER)
    await ctx.member_repo.add_member(ws.id, ctx.editor.id, role=WorkspaceRole.EDITOR)
    await ctx.member_repo.add_member(ws.id, ctx.viewer.id, role=WorkspaceRole.VIEWER)

    project = await ctx.project_repo.create(
        workspace_id=ws.id,
        name="Backend Core",
        description="Core services",
        status=ProjectStatus.ACTIVE,
    )
    return ws, project


@pytest.mark.anyio
async def test_create_project_by_editor_or_owner_succeeds(
    task_ctx: TaskTestContext,
    client: httpx.AsyncClient,
) -> None:
    """OWNER and EDITOR roles can create projects."""
    ws, _ = await _seed_workspace_and_project(task_ctx)

    app.dependency_overrides[get_current_user] = lambda: task_ctx.editor
    resp = await client.post(
        f"/api/v1/workspaces/{ws.id}/projects",
        json={"name": "Editor Project", "description": "Created by editor"},
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Editor Project"
    assert resp.json()["status"] == "ACTIVE"


@pytest.mark.anyio
async def test_create_project_by_viewer_returns_403(
    task_ctx: TaskTestContext,
    client: httpx.AsyncClient,
) -> None:
    """VIEWER cannot create projects (403 Forbidden)."""
    ws, _ = await _seed_workspace_and_project(task_ctx)

    app.dependency_overrides[get_current_user] = lambda: task_ctx.viewer
    resp = await client.post(
        f"/api/v1/workspaces/{ws.id}/projects",
        json={"name": "Viewer Project"},
    )
    assert resp.status_code == 403
    assert resp.json()["message"] == ERROR_PERMISSION_DENIED


@pytest.mark.anyio
async def test_create_project_by_outsider_returns_404(
    task_ctx: TaskTestContext,
    client: httpx.AsyncClient,
) -> None:
    """Outsider receives 404 to avoid resource enumeration."""
    ws, _ = await _seed_workspace_and_project(task_ctx)

    app.dependency_overrides[get_current_user] = lambda: task_ctx.outsider
    resp = await client.post(
        f"/api/v1/workspaces/{ws.id}/projects",
        json={"name": "Outsider Project"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_admin_accessing_nonexistent_workspace_returns_404(
    task_ctx: TaskTestContext,
    client: httpx.AsyncClient,
) -> None:
    """ADMIN accessing non-existent workspace must receive 404, not foreign key error."""
    app.dependency_overrides[get_current_user] = lambda: task_ctx.admin
    resp_create = await client.post(
        "/api/v1/workspaces/99999/projects",
        json={"name": "Ghost Project"},
    )
    assert resp_create.status_code == 404

    resp_list = await client.get("/api/v1/workspaces/99999/projects")
    assert resp_list.status_code == 404


@pytest.mark.anyio
async def test_archive_and_unarchive_project(
    task_ctx: TaskTestContext,
    client: httpx.AsyncClient,
) -> None:
    """Project can be archived and unarchived by owner; duplicates return 409 Conflict."""
    _, project = await _seed_workspace_and_project(task_ctx)

    app.dependency_overrides[get_current_user] = lambda: task_ctx.owner
    arch_resp = await client.patch(f"/api/v1/projects/{project.id}/archive")
    assert arch_resp.status_code == 200
    assert arch_resp.json()["status"] == "ARCHIVED"

    dup_arch = await client.patch(f"/api/v1/projects/{project.id}/archive")
    assert dup_arch.status_code == 409
    assert dup_arch.json()["message"] == ERROR_PROJECT_ALREADY_ARCHIVED

    unarch_resp = await client.patch(f"/api/v1/projects/{project.id}/unarchive")
    assert unarch_resp.status_code == 200
    assert unarch_resp.json()["status"] == "ACTIVE"

    dup_unarch = await client.patch(f"/api/v1/projects/{project.id}/unarchive")
    assert dup_unarch.status_code == 409
    assert dup_unarch.json()["message"] == ERROR_PROJECT_ALREADY_ACTIVE


@pytest.mark.anyio
async def test_editor_cannot_archive_or_unarchive_project(
    task_ctx: TaskTestContext,
    client: httpx.AsyncClient,
) -> None:
    """Only OWNER or ADMIN can archive/unarchive projects; EDITOR receives 403."""
    _, project = await _seed_workspace_and_project(task_ctx)

    app.dependency_overrides[get_current_user] = lambda: task_ctx.editor
    resp = await client.patch(f"/api/v1/projects/{project.id}/archive")
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_archived_project_blocks_modifications_and_delete(
    task_ctx: TaskTestContext,
    client: httpx.AsyncClient,
) -> None:
    """Writing to or deleting an archived project returns 409 Conflict."""
    _, project = await _seed_workspace_and_project(task_ctx)
    project.status = ProjectStatus.ARCHIVED

    app.dependency_overrides[get_current_user] = lambda: task_ctx.owner
    resp_update = await client.patch(
        f"/api/v1/projects/{project.id}",
        json={"name": "New Name"},
    )
    assert resp_update.status_code == 409
    assert resp_update.json()["message"] == ERROR_PROJECT_ARCHIVED

    resp_delete = await client.delete(f"/api/v1/projects/{project.id}")
    assert resp_delete.status_code == 409
    assert resp_delete.json()["message"] == ERROR_PROJECT_ARCHIVED


@pytest.mark.anyio
async def test_patch_project_clear_description_null(
    task_ctx: TaskTestContext,
    client: httpx.AsyncClient,
) -> None:
    """PATCH with explicit null description clears it properly."""
    _, project = await _seed_workspace_and_project(task_ctx)

    app.dependency_overrides[get_current_user] = lambda: task_ctx.owner
    resp = await client.patch(
        f"/api/v1/projects/{project.id}",
        json={"description": None},
    )
    assert resp.status_code == 200
    assert resp.json()["description"] is None


@pytest.mark.anyio
async def test_create_task_success(
    task_ctx: TaskTestContext,
    client: httpx.AsyncClient,
) -> None:
    """Task creation defaults to status TODO and assigns current_user as creator."""
    _, project = await _seed_workspace_and_project(task_ctx)

    app.dependency_overrides[get_current_user] = lambda: task_ctx.editor
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    resp = await client.post(
        f"/api/v1/projects/{project.id}/tasks",
        json={
            "title": "Build Architecture",
            "description": "FastAPI layered structure",
            "priority": "HIGH",
            "assignee_id": task_ctx.editor.id,
            "due_date": tomorrow.isoformat(),
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Build Architecture"
    assert data["status"] == "TODO"
    assert data["priority"] == "HIGH"
    assert data["created_by"] == task_ctx.editor.id
    assert data["assignee"]["email"] == task_ctx.editor.email
    assert data["creator"]["email"] == task_ctx.editor.email


@pytest.mark.anyio
async def test_create_task_due_date_in_past_returns_422(
    task_ctx: TaskTestContext,
    client: httpx.AsyncClient,
) -> None:
    """Due date in the past must be rejected with 422."""
    _, project = await _seed_workspace_and_project(task_ctx)

    app.dependency_overrides[get_current_user] = lambda: task_ctx.owner
    yesterday = datetime.now(UTC) - timedelta(days=1)
    resp = await client.post(
        f"/api/v1/projects/{project.id}/tasks",
        json={
            "title": "Past Task",
            "due_date": yesterday.isoformat(),
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "VALIDATION_ERROR"
    assert any(ERROR_DUE_DATE_IN_PAST in str(d) for d in resp.json().get("details", []))


@pytest.mark.anyio
async def test_create_task_assignee_outside_workspace_returns_400(
    task_ctx: TaskTestContext,
    client: httpx.AsyncClient,
) -> None:
    """Assigning user from outside the workspace must return 400 Bad Request."""
    _, project = await _seed_workspace_and_project(task_ctx)

    app.dependency_overrides[get_current_user] = lambda: task_ctx.owner
    resp = await client.post(
        f"/api/v1/projects/{project.id}/tasks",
        json={
            "title": "Outsider Task",
            "assignee_id": task_ctx.outsider.id,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == ERROR_ASSIGNEE_NOT_IN_WORKSPACE


@pytest.mark.anyio
async def test_create_task_assignee_viewer_returns_400(
    task_ctx: TaskTestContext,
    client: httpx.AsyncClient,
) -> None:
    """Assigning task to a VIEWER must return 400 as VIEWER lacks write capability."""
    _, project = await _seed_workspace_and_project(task_ctx)

    app.dependency_overrides[get_current_user] = lambda: task_ctx.owner
    resp = await client.post(
        f"/api/v1/projects/{project.id}/tasks",
        json={
            "title": "Viewer Assignee Task",
            "assignee_id": task_ctx.viewer.id,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == ERROR_ASSIGNEE_NOT_IN_WORKSPACE


@pytest.mark.anyio
async def test_create_task_in_archived_project_returns_409(
    task_ctx: TaskTestContext,
    client: httpx.AsyncClient,
) -> None:
    """Creating task in archived project returns 409 Conflict."""
    _, project = await _seed_workspace_and_project(task_ctx)
    project.status = ProjectStatus.ARCHIVED

    app.dependency_overrides[get_current_user] = lambda: task_ctx.owner
    resp = await client.post(
        f"/api/v1/projects/{project.id}/tasks",
        json={"title": "Should Fail"},
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == ERROR_PROJECT_ARCHIVED


@pytest.mark.anyio
async def test_viewer_cannot_create_or_update_task_returns_403(
    task_ctx: TaskTestContext,
    client: httpx.AsyncClient,
) -> None:
    """VIEWER receives 403 on write endpoints but can read tasks."""
    _, project = await _seed_workspace_and_project(task_ctx)
    task = await task_ctx.task_repo.create_task(
        project_id=project.id,
        created_by=task_ctx.owner.id,
        title="Initial Task",
    )

    app.dependency_overrides[get_current_user] = lambda: task_ctx.viewer
    create_resp = await client.post(
        f"/api/v1/projects/{project.id}/tasks",
        json={"title": "Viewer Attempt"},
    )
    assert create_resp.status_code == 403

    update_resp = await client.patch(
        f"/api/v1/tasks/{task.id}",
        json={"title": "Viewer Update"},
    )
    assert update_resp.status_code == 403

    status_resp = await client.patch(
        f"/api/v1/tasks/{task.id}/status",
        json={"status": "DONE"},
    )
    assert status_resp.status_code == 403

    delete_resp = await client.delete(f"/api/v1/tasks/{task.id}")
    assert delete_resp.status_code == 403

    get_resp = await client.get(f"/api/v1/tasks/{task.id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["title"] == "Initial Task"


@pytest.mark.anyio
async def test_outsider_accessing_task_returns_404(
    task_ctx: TaskTestContext,
    client: httpx.AsyncClient,
) -> None:
    """Outsider receives 404 on task detail to prevent resource enumeration."""
    _, project = await _seed_workspace_and_project(task_ctx)
    task = await task_ctx.task_repo.create_task(
        project_id=project.id,
        created_by=task_ctx.owner.id,
        title="Secret Task",
    )

    app.dependency_overrides[get_current_user] = lambda: task_ctx.outsider
    resp = await client.get(f"/api/v1/tasks/{task.id}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_patch_task_unassign_and_clear_fields(
    task_ctx: TaskTestContext,
    client: httpx.AsyncClient,
) -> None:
    """PATCH with null assignee_id, description, or due_date clears them properly."""
    _, project = await _seed_workspace_and_project(task_ctx)
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    task = await task_ctx.task_repo.create_task(
        project_id=project.id,
        created_by=task_ctx.owner.id,
        title="Task with assignee",
        description="Detailed description",
        priority=TaskPriority.HIGH,
        assignee_id=task_ctx.editor.id,
        due_date=tomorrow,
    )

    app.dependency_overrides[get_current_user] = lambda: task_ctx.owner
    resp = await client.patch(
        f"/api/v1/tasks/{task.id}",
        json={
            "assignee_id": None,
            "description": None,
            "due_date": None,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["assignee_id"] is None
    assert data["assignee"] is None
    assert data["description"] is None
    assert data["due_date"] is None


@pytest.mark.anyio
async def test_patch_task_priority_null_returns_422(
    task_ctx: TaskTestContext,
    client: httpx.AsyncClient,
) -> None:
    """PATCH with explicit null priority must return 422 Unprocessable Entity."""
    _, project = await _seed_workspace_and_project(task_ctx)
    task = await task_ctx.task_repo.create_task(
        project_id=project.id,
        created_by=task_ctx.owner.id,
        title="Task priority test",
    )

    app.dependency_overrides[get_current_user] = lambda: task_ctx.owner
    resp = await client.patch(
        f"/api/v1/tasks/{task.id}",
        json={"priority": None},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_list_tasks_filtering_and_pagination(
    task_ctx: TaskTestContext,
    client: httpx.AsyncClient,
) -> None:
    """Tasks list supports filtering by multiple statuses, priority, and paginated results."""
    _, project = await _seed_workspace_and_project(task_ctx)

    t1 = await task_ctx.task_repo.create_task(
        project_id=project.id,
        created_by=task_ctx.owner.id,
        title="Task 1",
        priority=TaskPriority.LOW,
        assignee_id=task_ctx.editor.id,
    )
    t1.status = TaskStatus.DONE

    t2 = await task_ctx.task_repo.create_task(
        project_id=project.id,
        created_by=task_ctx.owner.id,
        title="Task 2",
        priority=TaskPriority.HIGH,
        assignee_id=task_ctx.editor.id,
    )
    t2.status = TaskStatus.IN_PROGRESS

    t3 = await task_ctx.task_repo.create_task(
        project_id=project.id,
        created_by=task_ctx.owner.id,
        title="Task 3",
        priority=TaskPriority.HIGH,
        assignee_id=task_ctx.owner.id,
    )
    t3.status = TaskStatus.TODO

    app.dependency_overrides[get_current_user] = lambda: task_ctx.owner
    all_tasks = await client.get(f"/api/v1/projects/{project.id}/tasks")
    assert all_tasks.status_code == 200
    assert all_tasks.json()["total"] == 3

    filter_multi_status = await client.get(
        f"/api/v1/projects/{project.id}/tasks?status=TODO&status=DONE"
    )
    assert filter_multi_status.status_code == 200
    assert filter_multi_status.json()["total"] == 2

    filter_priority = await client.get(f"/api/v1/projects/{project.id}/tasks?priority=HIGH")
    assert filter_priority.status_code == 200
    assert filter_priority.json()["total"] == 2

    paginated = await client.get(f"/api/v1/projects/{project.id}/tasks?page=1&limit=2")
    assert paginated.status_code == 200
    assert len(paginated.json()["items"]) == 2
    assert paginated.json()["total_pages"] == 2
    assert paginated.json()["items"][0]["id"] > paginated.json()["items"][1]["id"]


@pytest.mark.anyio
async def test_update_task_and_quick_status_transition(
    task_ctx: TaskTestContext,
    client: httpx.AsyncClient,
) -> None:
    """PATCH endpoints allow full update and fast status transition."""
    _, project = await _seed_workspace_and_project(task_ctx)
    task = await task_ctx.task_repo.create_task(
        project_id=project.id,
        created_by=task_ctx.owner.id,
        title="Task to update",
    )

    app.dependency_overrides[get_current_user] = lambda: task_ctx.owner
    patch_resp = await client.patch(
        f"/api/v1/tasks/{task.id}",
        json={
            "title": "Updated Title",
            "priority": "URGENT",
            "assignee_id": task_ctx.editor.id,
        },
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["title"] == "Updated Title"
    assert patch_resp.json()["priority"] == "URGENT"
    assert patch_resp.json()["assignee_id"] == task_ctx.editor.id

    status_resp = await client.patch(
        f"/api/v1/tasks/{task.id}/status",
        json={"status": "DONE"},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "DONE"

    del_resp = await client.delete(f"/api/v1/tasks/{task.id}")
    assert del_resp.status_code == 200

    get_after_del = await client.get(f"/api/v1/tasks/{task.id}")
    assert get_after_del.status_code == 404


def test_project_and_task_repository_sql_compilation() -> None:
    """Verify that Project and Task repository queries compile valid SQL statements."""
    from sqlalchemy.dialects import mysql

    from app.models.workspace import Workspace, WorkspaceMember

    project_query = (
        select(Project, WorkspaceMember.role, Workspace.owner_id)
        .join(Workspace, Project.workspace_id == Workspace.id)
        .outerjoin(
            WorkspaceMember,
            (WorkspaceMember.workspace_id == Workspace.id) & (WorkspaceMember.user_id == 42),
        )
        .where(Project.id == 1)
    )
    project_sql = str(project_query.compile(dialect=mysql.dialect()))
    assert "JOIN workspaces ON projects.workspace_id = workspaces.id" in project_sql
    assert "LEFT OUTER JOIN workspace_members ON" in project_sql

    task_filter_query = (
        select(Task)
        .where(Task.project_id == 10, Task.status.in_([TaskStatus.TODO, TaskStatus.DONE]))
        .order_by(Task.id.desc())
    )
    task_sql = str(task_filter_query.compile(dialect=mysql.dialect()))
    assert "tasks.project_id = %s" in task_sql or "tasks.project_id =" in task_sql
    assert "tasks.status IN" in task_sql


@pytest.mark.anyio
async def test_real_project_and_task_repository_integration() -> None:
    """Test real SQL repository operations against MySQL engine if available; skip if offline."""
    settings = get_settings()
    engine = create_async_engine(
        settings.DATABASE_URL,
        connect_args={"connect_timeout": 2},
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    try:
        async with session_factory() as probe:
            await probe.execute(text("SELECT 1"))
            await probe.execute(text("SELECT id FROM projects LIMIT 1"))
            await probe.execute(text("SELECT id FROM tasks LIMIT 1"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"MySQL unavailable or unmigrated for task repository integration: {exc}")

    async with session_factory() as session:
        try:
            p_repo = ProjectRepository(session)
            t_repo = TaskRepository(session)

            user_row = (
                await session.execute(text("SELECT id FROM users ORDER BY id ASC LIMIT 1"))
            ).scalar()
            ws_row = (
                await session.execute(text("SELECT id FROM workspaces ORDER BY id ASC LIMIT 1"))
            ).scalar()
            if user_row is None or ws_row is None:
                pytest.skip("Integration test requires existing user and workspace in the database")

            test_uid = int(user_row)
            test_ws_id = int(ws_row)
            p = await p_repo.create(
                workspace_id=test_ws_id,
                name="Integration Project",
                status=ProjectStatus.ACTIVE,
            )
            await session.flush()

            t = await t_repo.create_task(
                project_id=p.id,
                created_by=test_uid,
                title="Integration Task",
            )
            await session.flush()

            resolved = await t_repo.get_with_project_and_workspace_role(t.id, test_uid)
            assert resolved is not None

            res_list = await t_repo.list_by_project(
                project_id=p.id,
                pagination=PaginationParams(page=1, limit=10),
                statuses=[TaskStatus.TODO],
            )
            assert any(item.id == t.id for item in res_list.items)

            await p_repo.delete(p.id)
            await session.flush()
        finally:
            await session.rollback()
            await engine.dispose()
