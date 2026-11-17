"""Unit, RBAC, and business logic tests for Projects and Tasks."""

import math
from collections.abc import Generator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
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
from app.models.enums import ProjectStatus, TaskPriority, TaskStatus, UserRole, WorkspaceRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.repositories.base import PaginationResult
from app.repositories.project import ProjectRepository
from app.repositories.task import TaskRepository
from app.repositories.user import UserRepository
from app.repositories.workspace import WorkspaceRepository
from app.repositories.workspace_member import WorkspaceMemberRepository
from app.schemas.common import PaginationParams
from app.services.project import ProjectService
from app.services.task import TaskService


class FakeAsyncSession:
    """In-memory async session recording commit/rollback actions."""

    def __init__(self) -> None:
        self.commit_count: int = 0
        self.rollback_count: int = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def refresh(self, instance: Any, attribute_names: Sequence[str] | None = None) -> None:
        _ = (instance, attribute_names)


class InMemoryUserRepository(UserRepository):
    """In-memory user repository backing test actors."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._users: dict[int, User] = {}

    def add_test_user(
        self,
        user_id: int,
        email: str,
        role: UserRole = UserRole.MEMBER,
        is_active: bool = True,
    ) -> User:
        user = User(
            id=user_id,
            email=email,
            full_name=f"User {user_id}",
            hashed_password="hash",
            role=role,
            is_active=is_active,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self._users[user_id] = user
        return user

    async def get_by_id(self, record_id: int) -> User | None:
        return self._users.get(record_id)


class InMemoryWorkspaceMemberRepository(WorkspaceMemberRepository):
    """In-memory membership store."""

    def __init__(self, session: AsyncSession, user_repo: InMemoryUserRepository) -> None:
        super().__init__(session)
        self.user_repo = user_repo
        self._members: dict[tuple[int, int], WorkspaceMember] = {}
        self._next_id: int = 1

    async def get_member(self, workspace_id: int, user_id: int) -> WorkspaceMember | None:
        member = self._members.get((workspace_id, user_id))
        if member is not None:
            member.user = self.user_repo._users.get(user_id)  # type: ignore[assignment]
        return member

    async def add_member(
        self,
        workspace_id: int,
        user_id: int,
        role: WorkspaceRole = WorkspaceRole.VIEWER,
    ) -> WorkspaceMember:
        member = WorkspaceMember(
            id=self._next_id,
            workspace_id=workspace_id,
            user_id=user_id,
            role=role,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self._next_id += 1
        member.user = self.user_repo._users.get(user_id)  # type: ignore[assignment]
        self._members[(workspace_id, user_id)] = member
        return member


class InMemoryWorkspaceRepository(WorkspaceRepository):
    """In-memory workspace store."""

    def __init__(
        self,
        session: AsyncSession,
        member_repo: InMemoryWorkspaceMemberRepository,
    ) -> None:
        super().__init__(session)
        self.member_repo = member_repo
        self._workspaces: dict[int, Workspace] = {}
        self._next_id: int = 1

    async def create(self, **kwargs: Any) -> Workspace:
        ws = Workspace(
            id=self._next_id,
            name=str(kwargs["name"]),
            owner_id=int(kwargs["owner_id"]),
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self._workspaces[self._next_id] = ws
        self._next_id += 1
        return ws

    async def get_by_id(self, record_id: int) -> Workspace | None:
        return self._workspaces.get(record_id)


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
        statuses: Sequence[TaskStatus] | None = None,
        priorities: Sequence[TaskPriority] | None = None,
        assignee_id: int | None = None,
    ) -> PaginationResult[Task]:
        matched = [t for t in self._tasks.values() if t.project_id == project_id]
        if statuses:
            matched = [t for t in matched if t.status in statuses]
        if priorities:
            matched = [t for t in matched if t.priority in priorities]
        if assignee_id is not None:
            matched = [t for t in matched if t.assignee_id == assignee_id]

        total = len(matched)
        matched.sort(key=lambda t: t.id, reverse=True)
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
        self.task_service = TaskService(
            session=self.session,
            task_repo=self.task_repo,
            project_repo=self.project_repo,
            workspace_repo=self.workspace_repo,
            member_repo=self.member_repo,
            user_repo=self.user_repo,
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
    ws = await ctx.workspace_repo.create(name="Team Workspace", owner_id=ctx.owner.id)
    await ctx.member_repo.add_member(ws.id, ctx.owner.id, role=WorkspaceRole.OWNER)
    await ctx.member_repo.add_member(ws.id, ctx.editor.id, role=WorkspaceRole.EDITOR)
    await ctx.member_repo.add_member(ws.id, ctx.viewer.id, role=WorkspaceRole.VIEWER)
    project = await ctx.project_repo.create(
        workspace_id=ws.id,
        name="Main Project",
        description="Core roadmap",
        status=ProjectStatus.ACTIVE,
    )
    return ws, project


@pytest.mark.anyio
async def test_create_project_by_editor_or_owner_succeeds(
    task_ctx: TaskTestContext,
) -> None:
    """EDITOR and OWNER can create projects inside workspace."""
    ws, _ = await _seed_workspace_and_project(task_ctx)

    app.dependency_overrides[get_current_user] = lambda: task_ctx.editor
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post(
            f"/api/v1/workspaces/{ws.id}/projects",
            json={"name": "Editor Project", "description": "Created by editor"},
        )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Editor Project"
    assert resp.json()["status"] == "ACTIVE"


@pytest.mark.anyio
async def test_create_project_by_viewer_returns_403(
    task_ctx: TaskTestContext,
) -> None:
    """VIEWER cannot create projects (403 Forbidden)."""
    ws, _ = await _seed_workspace_and_project(task_ctx)

    app.dependency_overrides[get_current_user] = lambda: task_ctx.viewer
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post(
            f"/api/v1/workspaces/{ws.id}/projects",
            json={"name": "Viewer Project"},
        )
    assert resp.status_code == 403
    assert resp.json()["message"] == ERROR_PERMISSION_DENIED


@pytest.mark.anyio
async def test_create_project_by_outsider_returns_404(
    task_ctx: TaskTestContext,
) -> None:
    """Outsider receives 404 to avoid resource enumeration."""
    ws, _ = await _seed_workspace_and_project(task_ctx)

    app.dependency_overrides[get_current_user] = lambda: task_ctx.outsider
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post(
            f"/api/v1/workspaces/{ws.id}/projects",
            json={"name": "Outsider Project"},
        )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_archive_and_unarchive_project(
    task_ctx: TaskTestContext,
) -> None:
    """Project can be archived and unarchived; duplicates return 409 Conflict."""
    _, project = await _seed_workspace_and_project(task_ctx)

    app.dependency_overrides[get_current_user] = lambda: task_ctx.owner
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        arch_resp = await ac.patch(f"/api/v1/projects/{project.id}/archive")
        assert arch_resp.status_code == 200
        assert arch_resp.json()["status"] == "ARCHIVED"

        dup_arch = await ac.patch(f"/api/v1/projects/{project.id}/archive")
        assert dup_arch.status_code == 409
        assert dup_arch.json()["message"] == ERROR_PROJECT_ALREADY_ARCHIVED

        unarch_resp = await ac.patch(f"/api/v1/projects/{project.id}/unarchive")
        assert unarch_resp.status_code == 200
        assert unarch_resp.json()["status"] == "ACTIVE"

        dup_unarch = await ac.patch(f"/api/v1/projects/{project.id}/unarchive")
        assert dup_unarch.status_code == 409
        assert dup_unarch.json()["message"] == ERROR_PROJECT_ALREADY_ACTIVE


@pytest.mark.anyio
async def test_update_archived_project_returns_409(
    task_ctx: TaskTestContext,
) -> None:
    """Writing to an archived project returns 409 Conflict."""
    _, project = await _seed_workspace_and_project(task_ctx)
    project.status = ProjectStatus.ARCHIVED

    app.dependency_overrides[get_current_user] = lambda: task_ctx.owner
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.patch(
            f"/api/v1/projects/{project.id}",
            json={"name": "New Name"},
        )
    assert resp.status_code == 409
    assert resp.json()["message"] == ERROR_PROJECT_ARCHIVED


@pytest.mark.anyio
async def test_create_task_success(task_ctx: TaskTestContext) -> None:
    """Task creation defaults to status TODO and assigns current_user as creator."""
    _, project = await _seed_workspace_and_project(task_ctx)

    app.dependency_overrides[get_current_user] = lambda: task_ctx.editor
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post(
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
) -> None:
    """Due date in the past must be rejected with 422."""
    _, project = await _seed_workspace_and_project(task_ctx)

    app.dependency_overrides[get_current_user] = lambda: task_ctx.owner
    yesterday = datetime.now(UTC) - timedelta(days=1)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post(
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
) -> None:
    """Assigning user from outside the workspace must return 400 Bad Request."""
    _, project = await _seed_workspace_and_project(task_ctx)

    app.dependency_overrides[get_current_user] = lambda: task_ctx.owner
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post(
            f"/api/v1/projects/{project.id}/tasks",
            json={
                "title": "Outsider Task",
                "assignee_id": task_ctx.outsider.id,
            },
        )
    assert resp.status_code == 400
    assert resp.json()["message"] == ERROR_ASSIGNEE_NOT_IN_WORKSPACE


@pytest.mark.anyio
async def test_create_task_in_archived_project_returns_409(
    task_ctx: TaskTestContext,
) -> None:
    """Creating task in archived project returns 409 Conflict."""
    _, project = await _seed_workspace_and_project(task_ctx)
    project.status = ProjectStatus.ARCHIVED

    app.dependency_overrides[get_current_user] = lambda: task_ctx.owner
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post(
            f"/api/v1/projects/{project.id}/tasks",
            json={"title": "Should Fail"},
        )
    assert resp.status_code == 409
    assert resp.json()["message"] == ERROR_PROJECT_ARCHIVED


@pytest.mark.anyio
async def test_viewer_cannot_create_or_update_task_returns_403(
    task_ctx: TaskTestContext,
) -> None:
    """VIEWER receives 403 on write endpoints but can read tasks."""
    _, project = await _seed_workspace_and_project(task_ctx)
    task = await task_ctx.task_repo.create_task(
        project_id=project.id,
        created_by=task_ctx.owner.id,
        title="Initial Task",
    )

    app.dependency_overrides[get_current_user] = lambda: task_ctx.viewer
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        create_resp = await ac.post(
            f"/api/v1/projects/{project.id}/tasks",
            json={"title": "Viewer Attempt"},
        )
        assert create_resp.status_code == 403

        update_resp = await ac.patch(
            f"/api/v1/tasks/{task.id}",
            json={"title": "Viewer Update"},
        )
        assert update_resp.status_code == 403

        status_resp = await ac.patch(
            f"/api/v1/tasks/{task.id}/status",
            json={"status": "DONE"},
        )
        assert status_resp.status_code == 403

        delete_resp = await ac.delete(f"/api/v1/tasks/{task.id}")
        assert delete_resp.status_code == 403

        get_resp = await ac.get(f"/api/v1/tasks/{task.id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["title"] == "Initial Task"


@pytest.mark.anyio
async def test_outsider_accessing_task_returns_404(
    task_ctx: TaskTestContext,
) -> None:
    """Outsider receives 404 on task detail to prevent resource enumeration."""
    _, project = await _seed_workspace_and_project(task_ctx)
    task = await task_ctx.task_repo.create_task(
        project_id=project.id,
        created_by=task_ctx.owner.id,
        title="Secret Task",
    )

    app.dependency_overrides[get_current_user] = lambda: task_ctx.outsider
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get(f"/api/v1/tasks/{task.id}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_list_tasks_filtering_and_pagination(
    task_ctx: TaskTestContext,
) -> None:
    """Tasks list supports filtering by status, priority, assignee, and paginated results."""
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
        assignee_id=task_ctx.viewer.id,
    )
    t2.status = TaskStatus.IN_PROGRESS

    t3 = await task_ctx.task_repo.create_task(
        project_id=project.id,
        created_by=task_ctx.owner.id,
        title="Task 3",
        priority=TaskPriority.HIGH,
        assignee_id=task_ctx.editor.id,
    )
    t3.status = TaskStatus.TODO

    app.dependency_overrides[get_current_user] = lambda: task_ctx.owner
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        all_tasks = await ac.get(f"/api/v1/projects/{project.id}/tasks")
        assert all_tasks.status_code == 200
        assert all_tasks.json()["total"] == 3

        filter_status = await ac.get(f"/api/v1/projects/{project.id}/tasks?status=DONE")
        assert filter_status.status_code == 200
        assert filter_status.json()["total"] == 1
        assert filter_status.json()["items"][0]["id"] == t1.id

        filter_assignee = await ac.get(
            f"/api/v1/projects/{project.id}/tasks?assignee_id={task_ctx.editor.id}"
        )
        assert filter_assignee.status_code == 200
        assert filter_assignee.json()["total"] == 2

        paginated = await ac.get(f"/api/v1/projects/{project.id}/tasks?page=1&limit=2")
        assert paginated.status_code == 200
        assert len(paginated.json()["items"]) == 2
        assert paginated.json()["total_pages"] == 2


@pytest.mark.anyio
async def test_update_task_and_quick_status_transition(
    task_ctx: TaskTestContext,
) -> None:
    """PATCH endpoints allow full update and fast status transition."""
    _, project = await _seed_workspace_and_project(task_ctx)
    task = await task_ctx.task_repo.create_task(
        project_id=project.id,
        created_by=task_ctx.owner.id,
        title="Task to update",
    )

    app.dependency_overrides[get_current_user] = lambda: task_ctx.owner
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        patch_resp = await ac.patch(
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

        status_resp = await ac.patch(
            f"/api/v1/tasks/{task.id}/status",
            json={"status": "DONE"},
        )
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "DONE"

        del_resp = await ac.delete(f"/api/v1/tasks/{task.id}")
        assert del_resp.status_code == 200

        get_after_del = await ac.get(f"/api/v1/tasks/{task.id}")
        assert get_after_del.status_code == 404
