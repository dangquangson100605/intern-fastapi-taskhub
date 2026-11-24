"""Unit, RBAC, and business logic tests for Labels and Comments."""

import math
from collections.abc import Generator, Sequence
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.constants import DEFAULT_LABEL_COLOR
from app.core.dependencies import (
    get_comment_repository,
    get_comment_service,
    get_current_user,
    get_db,
    get_label_repository,
    get_label_service,
    get_project_repository,
    get_task_repository,
    get_user_repository,
    get_workspace_member_repository,
    get_workspace_repository,
)
from app.core.messages import (
    ERROR_CANNOT_DELETE_OTHERS_COMMENT,
    ERROR_CANNOT_UPDATE_OTHERS_COMMENT,
    ERROR_LABEL_ALREADY_ASSIGNED,
    ERROR_LABEL_NAME_EXISTS,
    ERROR_LABEL_NOT_ASSIGNED,
    ERROR_PERMISSION_DENIED,
    ERROR_PROJECT_ARCHIVED,
)
from app.main import app
from app.models.comment import Comment
from app.models.enums import ProjectStatus, TaskPriority, TaskStatus, UserRole, WorkspaceRole
from app.models.label import Label
from app.models.project import Project
from app.models.task import Task
from app.models.workspace import Workspace
from app.repositories.base import PaginationResult
from app.repositories.comment import CommentRepository
from app.repositories.label import LabelRepository
from app.repositories.project import ProjectRepository
from app.repositories.task import TaskRepository
from app.schemas.common import PaginationParams
from app.services.comment import CommentService
from app.services.label import LabelService
from tests.conftest import (
    FakeAsyncSession,
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


class InMemoryTaskRepository(TaskRepository):
    """In-memory task repository with project lookup and caller permissions."""

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
        t.creator = cast(Any, self.user_repo._users.get(created_by))
        if assignee_id is not None:
            t.assignee = cast(Any, self.user_repo._users.get(assignee_id))
        self._tasks[self._next_id] = t
        self._next_id += 1
        return t

    async def get_by_id(self, record_id: int) -> Task | None:
        return self._tasks.get(record_id)

    async def get_with_project_and_workspace_role(
        self, task_id: int, user_id: int
    ) -> tuple[Task, Project, WorkspaceRole | None] | None:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        resolved = await self.project_repo.get_with_workspace_role(task.project_id, user_id)
        if resolved is None:
            return None
        project, role = resolved
        return task, project, role


class InMemoryLabelRepository(LabelRepository):
    """In-memory label repository backing test fixtures."""

    def __init__(
        self,
        session: AsyncSession,
        project_repo: InMemoryProjectRepository,
    ) -> None:
        super().__init__(session)
        self.project_repo = project_repo
        self._labels: dict[int, Label] = {}
        self._task_labels: set[tuple[int, int]] = set()
        self._next_id: int = 1

    async def create_label(
        self,
        project_id: int,
        name: str,
        color: str = DEFAULT_LABEL_COLOR,
    ) -> Label:
        for existing in self._labels.values():
            if existing.project_id == project_id and existing.name == name:
                raise IntegrityError(
                    "Duplicate entry for key uq_labels_project_name",
                    params=None,
                    orig=Exception("uq_labels_project_name"),
                )
        lbl = Label(
            id=self._next_id,
            project_id=project_id,
            name=name,
            color=color,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self._labels[self._next_id] = lbl
        self._next_id += 1
        return lbl

    async def get_by_id(self, record_id: int) -> Label | None:
        return self._labels.get(record_id)

    async def get_in_project(self, label_id: int, project_id: int) -> Label | None:
        lbl = self._labels.get(label_id)
        if lbl is None or lbl.project_id != project_id:
            return None
        return lbl

    async def get_with_project_and_workspace_role(
        self, label_id: int, user_id: int
    ) -> tuple[Label, Project, WorkspaceRole | None] | None:
        label = self._labels.get(label_id)
        if label is None:
            return None
        resolved = await self.project_repo.get_with_workspace_role(label.project_id, user_id)
        if resolved is None:
            return None
        project, role = resolved
        return label, project, role

    async def list_by_project(
        self, project_id: int, pagination: PaginationParams
    ) -> PaginationResult[Label]:
        matched = [lbl for lbl in self._labels.values() if lbl.project_id == project_id]
        matched.sort(key=lambda lbl: (lbl.created_at, lbl.id))
        total = len(matched)
        paged = matched[pagination.offset : pagination.offset + pagination.limit]
        return PaginationResult(
            items=paged,
            total=total,
            page=pagination.page,
            limit=pagination.limit,
            total_pages=math.ceil(total / pagination.limit) if pagination.limit > 0 else 0,
        )

    async def list_by_workspace(
        self, workspace_id: int, pagination: PaginationParams
    ) -> PaginationResult[Label]:
        project_ids = {
            p.id for p in self.project_repo._projects.values() if p.workspace_id == workspace_id
        }
        matched = [lbl for lbl in self._labels.values() if lbl.project_id in project_ids]
        matched.sort(key=lambda lbl: (lbl.created_at, lbl.id))
        total = len(matched)
        paged = matched[pagination.offset : pagination.offset + pagination.limit]
        return PaginationResult(
            items=paged,
            total=total,
            page=pagination.page,
            limit=pagination.limit,
            total_pages=math.ceil(total / pagination.limit) if pagination.limit > 0 else 0,
        )

    async def is_assigned_to_task(self, task_id: int, label_id: int) -> bool:
        return (task_id, label_id) in self._task_labels

    async def assign_to_task(self, task_id: int, label_id: int) -> None:
        if (task_id, label_id) in self._task_labels:
            raise IntegrityError(
                "Duplicate entry for key PRIMARY",
                params=None,
                orig=Exception("PRIMARY"),
            )
        self._task_labels.add((task_id, label_id))

    async def remove_from_task(self, task_id: int, label_id: int) -> bool:
        if (task_id, label_id) in self._task_labels:
            self._task_labels.remove((task_id, label_id))
            return True
        return False

    async def list_by_task(self, task_id: int) -> Sequence[Label]:
        label_ids = {lid for tid, lid in self._task_labels if tid == task_id}
        return [self._labels[lid] for lid in label_ids if lid in self._labels]

    async def delete(self, record_id: int) -> bool:
        if record_id in self._labels:
            del self._labels[record_id]
            self._task_labels = {pair for pair in self._task_labels if pair[1] != record_id}
            return True
        return False


class InMemoryCommentRepository(CommentRepository):
    """In-memory comment repository backing test fixtures."""

    def __init__(
        self,
        session: AsyncSession,
        task_repo: InMemoryTaskRepository,
        user_repo: InMemoryUserRepository,
    ) -> None:
        super().__init__(session)
        self.task_repo = task_repo
        self.user_repo = user_repo
        self._comments: dict[int, Comment] = {}
        self._next_id: int = 1

    async def create_comment(
        self,
        task_id: int,
        author_id: int,
        content: str,
    ) -> Comment:
        c = Comment(
            id=self._next_id,
            task_id=task_id,
            author_id=author_id,
            content=content,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        c.author = cast(Any, self.user_repo._users.get(author_id))
        self._comments[self._next_id] = c
        self._next_id += 1
        return c

    async def get_by_id(self, record_id: int) -> Comment | None:
        return self._comments.get(record_id)

    async def list_by_task(
        self, task_id: int, pagination: PaginationParams
    ) -> PaginationResult[Comment]:
        matched = [c for c in self._comments.values() if c.task_id == task_id]
        matched.sort(key=lambda c: (c.created_at, c.id))
        total = len(matched)
        paged = matched[pagination.offset : pagination.offset + pagination.limit]
        return PaginationResult(
            items=paged,
            total=total,
            page=pagination.page,
            limit=pagination.limit,
            total_pages=math.ceil(total / pagination.limit) if pagination.limit > 0 else 0,
        )

    async def get_with_task_and_workspace_role(
        self, comment_id: int, user_id: int
    ) -> tuple[Comment, Task, Project, WorkspaceRole | None] | None:
        comment = self._comments.get(comment_id)
        if comment is None:
            return None
        resolved = await self.task_repo.get_with_project_and_workspace_role(
            comment.task_id, user_id
        )
        if resolved is None:
            return None
        task, project, role = resolved
        return comment, task, project, role

    async def delete(self, record_id: int) -> bool:
        if record_id in self._comments:
            del self._comments[record_id]
            return True
        return False


class LabelCommentFakeAsyncSession(FakeAsyncSession):
    """In-memory async session simulating unique constraint checks on commit."""

    def __init__(self, label_repo: InMemoryLabelRepository) -> None:
        super().__init__()
        self.label_repo = label_repo

    async def commit(self) -> None:
        await super().commit()
        seen: set[tuple[int, str]] = set()
        for lbl in self.label_repo._labels.values():
            key = (lbl.project_id, lbl.name)
            if key in seen:
                raise IntegrityError(
                    "Duplicate entry for key uq_labels_project_name",
                    params=None,
                    orig=Exception("uq_labels_project_name"),
                )
            seen.add(key)


class LabelCommentTestContext:
    """Encapsulates test repositories, services, and actor accounts."""

    def __init__(self) -> None:
        self.label_repo = InMemoryLabelRepository(cast(AsyncSession, None), cast(Any, None))
        self.session = cast(AsyncSession, LabelCommentFakeAsyncSession(self.label_repo))
        self.user_repo = InMemoryUserRepository(self.session)
        self.member_repo = InMemoryWorkspaceMemberRepository(self.session, self.user_repo)
        self.workspace_repo = InMemoryWorkspaceRepository(self.session, self.member_repo)
        self.project_repo = InMemoryProjectRepository(
            self.session, self.workspace_repo, self.member_repo
        )
        self.task_repo = InMemoryTaskRepository(self.session, self.project_repo, self.user_repo)
        self.label_repo.session = self.session
        self.label_repo.project_repo = self.project_repo
        self.comment_repo = InMemoryCommentRepository(
            self.session, self.task_repo, self.user_repo
        )

        self.label_service = LabelService(
            session=self.session,
            label_repo=self.label_repo,
            project_repo=self.project_repo,
            task_repo=self.task_repo,
            workspace_repo=self.workspace_repo,
            member_repo=self.member_repo,
        )
        self.comment_service = CommentService(
            session=self.session,
            comment_repo=self.comment_repo,
            task_repo=self.task_repo,
        )

        self.owner = self.user_repo.add_test_user(1, "owner@example.com")
        self.editor = self.user_repo.add_test_user(2, "editor@example.com")
        self.viewer = self.user_repo.add_test_user(3, "viewer@example.com")
        self.outsider = self.user_repo.add_test_user(4, "outsider@example.com")
        self.admin = self.user_repo.add_test_user(5, "admin@example.com", role=UserRole.ADMIN)


@pytest.fixture
def lc_ctx() -> Generator[LabelCommentTestContext, None, None]:
    """Wire in-memory test repositories into dependency overrides."""
    ctx = LabelCommentTestContext()
    app.dependency_overrides[get_db] = lambda: ctx.session
    app.dependency_overrides[get_user_repository] = lambda: ctx.user_repo
    app.dependency_overrides[get_workspace_repository] = lambda: ctx.workspace_repo
    app.dependency_overrides[get_workspace_member_repository] = lambda: ctx.member_repo
    app.dependency_overrides[get_project_repository] = lambda: ctx.project_repo
    app.dependency_overrides[get_task_repository] = lambda: ctx.task_repo
    app.dependency_overrides[get_label_repository] = lambda: ctx.label_repo
    app.dependency_overrides[get_comment_repository] = lambda: ctx.comment_repo
    app.dependency_overrides[get_label_service] = lambda: ctx.label_service
    app.dependency_overrides[get_comment_service] = lambda: ctx.comment_service
    yield ctx
    app.dependency_overrides.clear()


async def _seed_workspace_project_and_task(
    ctx: LabelCommentTestContext,
) -> tuple[Workspace, Project, Task]:
    """Helper creating a workspace with members, active project, and a task."""
    await ctx.workspace_repo.create(name="Preceding Workspace", owner_id=ctx.owner.id)
    ws = await ctx.workspace_repo.create(name="Product Workspace", owner_id=ctx.owner.id)
    await ctx.member_repo.add_member(ws.id, ctx.owner.id, role=WorkspaceRole.OWNER)
    await ctx.member_repo.add_member(ws.id, ctx.editor.id, role=WorkspaceRole.EDITOR)
    await ctx.member_repo.add_member(ws.id, ctx.viewer.id, role=WorkspaceRole.VIEWER)

    project = await ctx.project_repo.create(
        workspace_id=ws.id,
        name="Mobile App",
        description="iOS and Android",
        status=ProjectStatus.ACTIVE,
    )
    task = await ctx.task_repo.create_task(
        project_id=project.id,
        created_by=ctx.owner.id,
        title="Implement Login Flow",
        description="Social and email login",
    )
    return ws, project, task


@pytest.mark.anyio
async def test_create_label_valid_hex_color_succeeds(
    client: httpx.AsyncClient, lc_ctx: LabelCommentTestContext
) -> None:
    """Verify that creating a label with a valid 6-char or 3-char HEX color succeeds."""
    _, project, _ = await _seed_workspace_project_and_task(lc_ctx)
    app.dependency_overrides[get_current_user] = lambda: lc_ctx.editor

    response = await client.post(
        f"/api/v1/projects/{project.id}/labels",
        json={"name": "Bug", "color": "#EF4444"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Bug"
    assert data["color"] == "#EF4444"
    assert data["project_id"] == project.id


@pytest.mark.anyio
async def test_create_duplicate_label_name_in_project_returns_409(
    client: httpx.AsyncClient, lc_ctx: LabelCommentTestContext
) -> None:
    """Verify that creating two labels with the same name in the same project returns 409 Conflict."""
    _, project, _ = await _seed_workspace_project_and_task(lc_ctx)
    app.dependency_overrides[get_current_user] = lambda: lc_ctx.editor

    resp1 = await client.post(
        f"/api/v1/projects/{project.id}/labels",
        json={"name": "Bug", "color": "#EF4444"},
    )
    assert resp1.status_code == 201

    resp2 = await client.post(
        f"/api/v1/projects/{project.id}/labels",
        json={"name": "Bug", "color": "#3B82F6"},
    )
    assert resp2.status_code == 409
    assert resp2.json()["message"] == ERROR_LABEL_NAME_EXISTS


@pytest.mark.anyio
async def test_update_label_duplicate_name_returns_409(
    client: httpx.AsyncClient, lc_ctx: LabelCommentTestContext
) -> None:
    """Verify that updating a label to a name already used in the same project returns 409 Conflict."""
    _, project, _ = await _seed_workspace_project_and_task(lc_ctx)
    app.dependency_overrides[get_current_user] = lambda: lc_ctx.editor

    lbl1 = await lc_ctx.label_repo.create_label(project.id, "Bug", "#EF4444")
    lbl2 = await lc_ctx.label_repo.create_label(project.id, "Feature", "#10B981")

    resp = await client.patch(
        f"/api/v1/labels/{lbl2.id}",
        json={"name": lbl1.name},
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == ERROR_LABEL_NAME_EXISTS


@pytest.mark.anyio
async def test_create_label_invalid_hex_color_returns_422(
    client: httpx.AsyncClient, lc_ctx: LabelCommentTestContext
) -> None:
    """Verify that invalid HEX colors like 'red', '123', or '#GGGGGG' are rejected with 422."""
    _, project, _ = await _seed_workspace_project_and_task(lc_ctx)
    app.dependency_overrides[get_current_user] = lambda: lc_ctx.editor

    for invalid_color in ["red", "123", "#GGGGGG", "#12345"]:
        response = await client.post(
            f"/api/v1/projects/{project.id}/labels",
            json={"name": "Invalid", "color": invalid_color},
        )
        assert response.status_code == 422


@pytest.mark.anyio
async def test_create_label_viewer_returns_403(
    client: httpx.AsyncClient, lc_ctx: LabelCommentTestContext
) -> None:
    """Verify that workspace VIEWER is forbidden from creating labels."""
    _, project, _ = await _seed_workspace_project_and_task(lc_ctx)
    app.dependency_overrides[get_current_user] = lambda: lc_ctx.viewer

    response = await client.post(
        f"/api/v1/projects/{project.id}/labels",
        json={"name": "Feature", "color": "#10B981"},
    )
    assert response.status_code == 403
    assert response.json()["message"] == ERROR_PERMISSION_DENIED


@pytest.mark.anyio
async def test_create_label_archived_project_returns_409(
    client: httpx.AsyncClient, lc_ctx: LabelCommentTestContext
) -> None:
    """Verify that creating labels in an archived project returns 409 Conflict."""
    _, project, _ = await _seed_workspace_project_and_task(lc_ctx)
    project.status = ProjectStatus.ARCHIVED
    app.dependency_overrides[get_current_user] = lambda: lc_ctx.owner

    response = await client.post(
        f"/api/v1/projects/{project.id}/labels",
        json={"name": "Blocked", "color": "#10B981"},
    )
    assert response.status_code == 409
    assert response.json()["message"] == ERROR_PROJECT_ARCHIVED


@pytest.mark.anyio
async def test_assign_label_to_task_succeeds_and_duplicate_returns_409(
    client: httpx.AsyncClient, lc_ctx: LabelCommentTestContext
) -> None:
    """Verify assigning a label to a task succeeds and duplicate assignment triggers 409."""
    _, project, task = await _seed_workspace_project_and_task(lc_ctx)
    label = await lc_ctx.label_repo.create_label(project.id, "Urgent", "#EF4444")
    app.dependency_overrides[get_current_user] = lambda: lc_ctx.editor

    response = await client.post(f"/api/v1/tasks/{task.id}/labels/{label.id}")
    assert response.status_code == 200

    dup_response = await client.post(f"/api/v1/tasks/{task.id}/labels/{label.id}")
    assert dup_response.status_code == 409
    assert dup_response.json()["message"] == ERROR_LABEL_ALREADY_ASSIGNED


@pytest.mark.anyio
async def test_assign_cross_project_label_returns_404(
    client: httpx.AsyncClient, lc_ctx: LabelCommentTestContext
) -> None:
    """Verify assigning a label from Project B to Project A task returns 404 to avoid ID disclosure."""
    ws, _, task_a = await _seed_workspace_project_and_task(lc_ctx)
    project_b = await lc_ctx.project_repo.create(
        workspace_id=ws.id, name="Project B", status=ProjectStatus.ACTIVE
    )
    label_b = await lc_ctx.label_repo.create_label(project_b.id, "Frontend", "#3B82F6")

    app.dependency_overrides[get_current_user] = lambda: lc_ctx.editor

    response = await client.post(f"/api/v1/tasks/{task_a.id}/labels/{label_b.id}")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_remove_label_from_task(
    client: httpx.AsyncClient, lc_ctx: LabelCommentTestContext
) -> None:
    """Verify removing a label from a task succeeds and removing unassigned returns 404."""
    _, project, task = await _seed_workspace_project_and_task(lc_ctx)
    label = await lc_ctx.label_repo.create_label(project.id, "Backend", "#10B981")
    await lc_ctx.label_repo.assign_to_task(task.id, label.id)

    app.dependency_overrides[get_current_user] = lambda: lc_ctx.editor

    response = await client.delete(f"/api/v1/tasks/{task.id}/labels/{label.id}")
    assert response.status_code == 200

    not_assigned = await client.delete(f"/api/v1/tasks/{task.id}/labels/{label.id}")
    assert not_assigned.status_code == 404
    assert not_assigned.json()["message"] == ERROR_LABEL_NOT_ASSIGNED


@pytest.mark.anyio
async def test_list_project_labels_pagination(
    client: httpx.AsyncClient, lc_ctx: LabelCommentTestContext
) -> None:
    """Verify project label listing supports pagination parameters."""
    _, project, _ = await _seed_workspace_project_and_task(lc_ctx)
    for i in range(4):
        await lc_ctx.label_repo.create_label(project.id, f"Label {i}", "#10B981")

    app.dependency_overrides[get_current_user] = lambda: lc_ctx.editor

    response = await client.get(f"/api/v1/projects/{project.id}/labels?page=1&limit=2")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 4
    assert data["page"] == 1
    assert data["limit"] == 2
    assert data["total_pages"] == 2
    assert len(data["items"]) == 2


@pytest.mark.anyio
async def test_create_comment_succeeds_and_empty_content_returns_422(
    client: httpx.AsyncClient, lc_ctx: LabelCommentTestContext
) -> None:
    """Verify comment creation with non-empty string succeeds and empty string is rejected."""
    _, _, task = await _seed_workspace_project_and_task(lc_ctx)
    app.dependency_overrides[get_current_user] = lambda: lc_ctx.editor

    response = await client.post(
        f"/api/v1/tasks/{task.id}/comments",
        json={"content": "Great work on this task!"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["content"] == "Great work on this task!"
    assert data["task_id"] == task.id
    assert data["author"]["id"] == lc_ctx.editor.id

    empty_response = await client.post(
        f"/api/v1/tasks/{task.id}/comments",
        json={"content": ""},
    )
    assert empty_response.status_code == 422


@pytest.mark.anyio
async def test_create_comment_viewer_returns_403(
    client: httpx.AsyncClient, lc_ctx: LabelCommentTestContext
) -> None:
    """Verify that workspace VIEWER is forbidden from creating comments."""
    _, _, task = await _seed_workspace_project_and_task(lc_ctx)
    app.dependency_overrides[get_current_user] = lambda: lc_ctx.viewer

    response = await client.post(
        f"/api/v1/tasks/{task.id}/comments",
        json={"content": "Viewer comment attempt"},
    )
    assert response.status_code == 403
    assert response.json()["message"] == ERROR_PERMISSION_DENIED


@pytest.mark.anyio
async def test_create_comment_outsider_returns_404(
    client: httpx.AsyncClient, lc_ctx: LabelCommentTestContext
) -> None:
    """Verify that user outside workspace receives 404 Not Found to prevent resource enumeration."""
    _, _, task = await _seed_workspace_project_and_task(lc_ctx)
    app.dependency_overrides[get_current_user] = lambda: lc_ctx.outsider

    response = await client.post(
        f"/api/v1/tasks/{task.id}/comments",
        json={"content": "Outsider comment attempt"},
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_list_comments_chronological_order(
    client: httpx.AsyncClient, lc_ctx: LabelCommentTestContext
) -> None:
    """Verify listing task comments returns them in ascending chronological order."""
    _, _, task = await _seed_workspace_project_and_task(lc_ctx)
    await lc_ctx.comment_repo.create_comment(task.id, lc_ctx.owner.id, "First comment")
    await lc_ctx.comment_repo.create_comment(task.id, lc_ctx.editor.id, "Second comment")

    app.dependency_overrides[get_current_user] = lambda: lc_ctx.viewer

    response = await client.get(f"/api/v1/tasks/{task.id}/comments")
    assert response.status_code == 200
    data = response.json()
    items = data["items"]
    assert data["total"] == 2
    assert len(items) == 2
    assert items[0]["content"] == "First comment"
    assert items[1]["content"] == "Second comment"


@pytest.mark.anyio
async def test_list_comments_pagination(
    client: httpx.AsyncClient, lc_ctx: LabelCommentTestContext
) -> None:
    """Verify comment listing supports pagination parameters (page, limit, total, total_pages)."""
    _, _, task = await _seed_workspace_project_and_task(lc_ctx)
    for i in range(5):
        await lc_ctx.comment_repo.create_comment(task.id, lc_ctx.owner.id, f"Comment {i}")

    app.dependency_overrides[get_current_user] = lambda: lc_ctx.editor

    response = await client.get(f"/api/v1/tasks/{task.id}/comments?page=1&limit=2")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 5
    assert data["page"] == 1
    assert data["limit"] == 2
    assert data["total_pages"] == 3
    assert len(data["items"]) == 2
    assert data["items"][0]["content"] == "Comment 0"
    assert data["items"][1]["content"] == "Comment 1"

    page2_resp = await client.get(f"/api/v1/tasks/{task.id}/comments?page=2&limit=2")
    assert page2_resp.status_code == 200
    page2_data = page2_resp.json()
    assert len(page2_data["items"]) == 2
    assert page2_data["items"][0]["content"] == "Comment 2"


@pytest.mark.anyio
async def test_update_comment_author_and_admin_succeeds_non_author_editor_returns_403(
    client: httpx.AsyncClient, lc_ctx: LabelCommentTestContext
) -> None:
    """Verify author and admin can update comment, while other editors are forbidden."""
    ws, _, task = await _seed_workspace_project_and_task(lc_ctx)
    comment = await lc_ctx.comment_repo.create_comment(
        task.id, lc_ctx.editor.id, "Original comment content"
    )

    other_user = lc_ctx.user_repo.add_test_user(98, "other_editor_2@example.com")
    await lc_ctx.member_repo.add_member(ws.id, other_user.id, role=WorkspaceRole.EDITOR)
    app.dependency_overrides[get_current_user] = lambda: other_user

    forbidden_resp = await client.patch(
        f"/api/v1/comments/{comment.id}",
        json={"content": "Malicious edit"},
    )
    assert forbidden_resp.status_code == 403
    assert forbidden_resp.json()["message"] == ERROR_CANNOT_UPDATE_OTHERS_COMMENT

    app.dependency_overrides[get_current_user] = lambda: lc_ctx.editor
    author_resp = await client.patch(
        f"/api/v1/comments/{comment.id}",
        json={"content": "Author updated content"},
    )
    assert author_resp.status_code == 200
    assert author_resp.json()["content"] == "Author updated content"

    app.dependency_overrides[get_current_user] = lambda: lc_ctx.admin
    admin_resp = await client.patch(
        f"/api/v1/comments/{comment.id}",
        json={"content": "Admin updated content"},
    )
    assert admin_resp.status_code == 200
    assert admin_resp.json()["content"] == "Admin updated content"


@pytest.mark.anyio
async def test_update_comment_archived_project_returns_409(
    client: httpx.AsyncClient, lc_ctx: LabelCommentTestContext
) -> None:
    """Verify updating a comment in an archived project returns 409 Conflict."""
    _, project, task = await _seed_workspace_project_and_task(lc_ctx)
    comment = await lc_ctx.comment_repo.create_comment(
        task.id, lc_ctx.editor.id, "Comment before archive"
    )
    project.status = ProjectStatus.ARCHIVED
    app.dependency_overrides[get_current_user] = lambda: lc_ctx.editor

    response = await client.patch(
        f"/api/v1/comments/{comment.id}",
        json={"content": "Attempted edit after archive"},
    )
    assert response.status_code == 409
    assert response.json()["message"] == ERROR_PROJECT_ARCHIVED


@pytest.mark.anyio
async def test_comment_deletion_authorization_rules(
    client: httpx.AsyncClient, lc_ctx: LabelCommentTestContext
) -> None:
    """Verify that author, workspace owner, and admin can delete comments, but other editors cannot."""
    ws, _, task = await _seed_workspace_project_and_task(lc_ctx)

    author_comment = await lc_ctx.comment_repo.create_comment(
        task.id, lc_ctx.editor.id, "Comment by editor"
    )

    other_user = lc_ctx.user_repo.add_test_user(99, "other_editor@example.com")
    await lc_ctx.member_repo.add_member(ws.id, other_user.id, role=WorkspaceRole.EDITOR)
    app.dependency_overrides[get_current_user] = lambda: other_user

    forbidden_resp = await client.delete(f"/api/v1/comments/{author_comment.id}")
    assert forbidden_resp.status_code == 403
    assert forbidden_resp.json()["message"] == ERROR_CANNOT_DELETE_OTHERS_COMMENT

    app.dependency_overrides[get_current_user] = lambda: lc_ctx.editor
    author_delete = await client.delete(f"/api/v1/comments/{author_comment.id}")
    assert author_delete.status_code == 200

    owner_test_comment = await lc_ctx.comment_repo.create_comment(
        task.id, lc_ctx.editor.id, "Another comment"
    )
    app.dependency_overrides[get_current_user] = lambda: lc_ctx.owner
    owner_delete = await client.delete(f"/api/v1/comments/{owner_test_comment.id}")
    assert owner_delete.status_code == 200

    admin_test_comment = await lc_ctx.comment_repo.create_comment(
        task.id, lc_ctx.editor.id, "Third comment"
    )
    app.dependency_overrides[get_current_user] = lambda: lc_ctx.admin
    admin_delete = await client.delete(f"/api/v1/comments/{admin_test_comment.id}")
    assert admin_delete.status_code == 200


@pytest.mark.anyio
async def test_delete_comment_archived_project_non_author_returns_403(
    client: httpx.AsyncClient, lc_ctx: LabelCommentTestContext
) -> None:
    """Verify non-author editor gets 403 Forbidden (not 409) when trying to delete in archived project."""
    ws, project, task = await _seed_workspace_project_and_task(lc_ctx)
    comment = await lc_ctx.comment_repo.create_comment(
        task.id, lc_ctx.editor.id, "Editor comment"
    )
    project.status = ProjectStatus.ARCHIVED

    other_user = lc_ctx.user_repo.add_test_user(97, "other_editor_3@example.com")
    await lc_ctx.member_repo.add_member(ws.id, other_user.id, role=WorkspaceRole.EDITOR)
    app.dependency_overrides[get_current_user] = lambda: other_user

    response = await client.delete(f"/api/v1/comments/{comment.id}")
    assert response.status_code == 403
    assert response.json()["message"] == ERROR_CANNOT_DELETE_OTHERS_COMMENT


@pytest.mark.anyio
async def test_sql_joined_queries_compile_successfully() -> None:
    """Verify that Label and Comment joined SQL queries compile cleanly under SQLAlchemy."""
    label_query = (
        select(Label, Project, Workspace.owner_id)
        .join(Project, Label.project_id == Project.id)
        .join(Workspace, Project.workspace_id == Workspace.id)
        .where(Label.id == 1)
    )
    compiled_label = str(label_query.compile(compile_kwargs={"literal_binds": True}))
    assert "JOIN projects ON labels.project_id = projects.id" in compiled_label
    assert "JOIN workspaces ON projects.workspace_id = workspaces.id" in compiled_label

    comment_query = (
        select(Comment, Task, Project, Workspace.owner_id)
        .join(Task, Comment.task_id == Task.id)
        .join(Project, Task.project_id == Project.id)
        .join(Workspace, Project.workspace_id == Workspace.id)
        .where(Comment.id == 1)
    )
    compiled_comment = str(comment_query.compile(compile_kwargs={"literal_binds": True}))
    assert "JOIN tasks ON comments.task_id = tasks.id" in compiled_comment
    assert "JOIN projects ON tasks.project_id = projects.id" in compiled_comment


@pytest.mark.anyio
async def test_real_label_and_comment_repository_integration() -> None:
    """Test real Label and Comment repository operations against MySQL when available."""
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
            await probe.execute(text("SELECT id FROM users LIMIT 1"))
            await probe.execute(text("SELECT id FROM projects LIMIT 1"))
            await probe.execute(text("SELECT id FROM tasks LIMIT 1"))
            await probe.execute(text("SELECT id FROM labels LIMIT 1"))
            await probe.execute(text("SELECT id FROM comments LIMIT 1"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"MySQL unavailable or unmigrated for label/comment integration: {exc}")

    async with session_factory() as session:
        try:
            label_repo = LabelRepository(session)
            comment_repo = CommentRepository(session)
            task_repo = TaskRepository(session)

            user_row = (
                await session.execute(text("SELECT id FROM users ORDER BY id ASC LIMIT 1"))
            ).scalar()
            proj_row = (
                await session.execute(text("SELECT id FROM projects ORDER BY id ASC LIMIT 1"))
            ).scalar()
            if user_row is None or proj_row is None:
                pytest.skip("Integration test requires existing user and project in database")

            test_uid = int(user_row)
            test_proj_id = int(proj_row)

            label = await label_repo.create_label(
                project_id=test_proj_id,
                name="Integration Label",
                color="#3B82F6",
            )
            await session.flush()
            assert label.id is not None

            resolved_label = await label_repo.get_with_project_and_workspace_role(
                label.id, test_uid
            )
            assert resolved_label is not None
            assert resolved_label[0].id == label.id

            in_project_label = await label_repo.get_in_project(label.id, test_proj_id)
            assert in_project_label is not None
            assert in_project_label.id == label.id

            task = await task_repo.create_task(
                project_id=test_proj_id,
                created_by=test_uid,
                title="Task for Label Integration",
            )
            await session.flush()

            await label_repo.assign_to_task(task.id, label.id)
            await session.flush()

            is_assigned = await label_repo.is_assigned_to_task(task.id, label.id)
            assert is_assigned is True

            task_labels = await label_repo.list_by_task(task.id)
            assert any(lbl.id == label.id for lbl in task_labels)

            removed = await label_repo.remove_from_task(task.id, label.id)
            assert removed is True

            comment = await comment_repo.create_comment(
                task_id=task.id,
                author_id=test_uid,
                content="Real integration comment",
            )
            await session.flush()
            assert comment.id is not None

            resolved_comment = await comment_repo.get_with_task_and_workspace_role(
                comment.id, test_uid
            )
            assert resolved_comment is not None
            assert resolved_comment[0].id == comment.id

            task_comments = await comment_repo.list_by_task(
                task.id, PaginationParams(page=1, limit=10)
            )
            assert any(c.id == comment.id for c in task_comments.items)

            proj_labels = await label_repo.list_by_project(
                test_proj_id, PaginationParams(page=1, limit=10)
            )
            assert any(lbl.id == label.id for lbl in proj_labels.items)
        finally:
            await session.rollback()
            await engine.dispose()
