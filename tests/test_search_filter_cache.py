"""Comprehensive tests for Day 7: search, multi-criteria filtering, pagination, sorting, and Redis caching."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy.dialects import mysql

from app.core.cache import CacheService
from app.core.dependencies import (
    get_cache_service,
    get_current_user,
    get_db,
    get_label_repository,
    get_label_service,
    get_project_repository,
    get_project_service,
    get_task_repository,
    get_task_service,
    get_user_repository,
    get_workspace_member_repository,
    get_workspace_repository,
)
from app.core.messages import ERROR_INVALID_DATE_RANGE
from app.main import app
from app.models.enums import (
    ProjectStatus,
    SortOrder,
    TaskPriority,
    TaskSortBy,
    TaskStatus,
    WorkspaceRole,
)
from app.models.label import Label
from app.models.project import Project
from app.models.task import Task
from app.models.workspace import Workspace
from app.repositories.base import PaginationResult
from app.repositories.label import LabelRepository
from app.repositories.project import ProjectRepository
from app.repositories.task import TaskRepository
from app.schemas.common import PaginationParams
from app.services.label import LabelService
from app.services.project import ProjectService
from app.services.task import TaskService
from tests.conftest import (
    FakeAsyncSession,
    FakeRedis,
    InMemoryUserRepository,
    InMemoryWorkspaceMemberRepository,
    InMemoryWorkspaceRepository,
)


class InMemoryLabelRepoForDay7(LabelRepository):
    """In-memory label repository supporting label assignment to tasks."""

    def __init__(self, session: Any, project_repo: Any) -> None:
        super().__init__(session)
        self.project_repo = project_repo
        self._labels: dict[int, Label] = {}
        self._task_labels: set[tuple[int, int]] = set()
        self._next_id: int = 1

    async def create_label(
        self,
        project_id: int,
        name: str,
        color: str = "#6B7280",
    ) -> Label:
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
        if lbl is not None and lbl.project_id == project_id:
            return lbl
        return None

    async def get_with_project_and_workspace_role(
        self, label_id: int, user_id: int
    ) -> tuple[Label, Project, WorkspaceRole | None] | None:
        lbl = self._labels.get(label_id)
        if lbl is None:
            return None
        res = await self.project_repo.get_with_workspace_role(lbl.project_id, user_id)
        if res is None:
            return None
        project, role = res
        return lbl, project, role

    async def assign_to_task(self, task_id: int, label_id: int) -> None:
        self._task_labels.add((task_id, label_id))

    async def remove_from_task(self, task_id: int, label_id: int) -> bool:
        if (task_id, label_id) in self._task_labels:
            self._task_labels.remove((task_id, label_id))
            return True
        return False

    async def is_assigned_to_task(self, task_id: int, label_id: int) -> bool:
        return (task_id, label_id) in self._task_labels

    async def list_by_task(self, task_id: int) -> list[Label]:
        label_ids = [lid for tid, lid in self._task_labels if tid == task_id]
        return [self._labels[lid] for lid in label_ids if lid in self._labels]

    async def delete(self, record_id: int) -> bool:
        if record_id in self._labels:
            del self._labels[record_id]
            self._task_labels = {pair for pair in self._task_labels if pair[1] != record_id}
            return True
        return False


class InMemoryTaskRepoForDay7(TaskRepository):
    """In-memory task repository implementing Day 7 searching, filtering, and sorting."""

    def __init__(
        self,
        session: Any,
        project_repo: Any,
        user_repo: InMemoryUserRepository,
        label_repo: InMemoryLabelRepoForDay7,
    ) -> None:
        super().__init__(session)
        self.project_repo = project_repo
        self.user_repo = user_repo
        self.label_repo = label_repo
        self._tasks: dict[int, Task] = {}
        self._next_id: int = 1
        self.list_call_count: int = 0

    def _attach_relations(self, task: Task) -> Task:
        task.creator = self.user_repo._users.get(task.created_by)  # type: ignore[assignment]
        if task.assignee_id is not None:
            task.assignee = self.user_repo._users.get(task.assignee_id)  # type: ignore[assignment]
        else:
            task.assignee = None
        task.labels = [  # type: ignore[assignment]
            lbl
            for tid, lid in self.label_repo._task_labels
            if tid == task.id and (lbl := self.label_repo._labels.get(lid)) is not None
        ]
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
        statuses: Any = None,
        priorities: Any = None,
        assignee_id: int | None = None,
        due_date_from: datetime | None = None,
        due_date_to: datetime | None = None,
        label_id: int | None = None,
        sort_by: TaskSortBy = TaskSortBy.CREATED_AT,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> PaginationResult[Task]:
        self.list_call_count += 1
        matched = [t for t in self._tasks.values() if t.project_id == project_id]

        if search:
            kw = search.lower()
            matched = [
                t
                for t in matched
                if (t.title and kw in t.title.lower())
                or (t.description and kw in t.description.lower())
            ]

        if statuses:
            matched = [t for t in matched if t.status in statuses]

        if priorities:
            matched = [t for t in matched if t.priority in priorities]

        if assignee_id is not None:
            matched = [t for t in matched if t.assignee_id == assignee_id]

        if due_date_from is not None:
            matched = [
                t for t in matched if t.due_date is not None and t.due_date >= due_date_from
            ]

        if due_date_to is not None:
            matched = [t for t in matched if t.due_date is not None and t.due_date <= due_date_to]

        if label_id is not None:
            matched = [
                t
                for t in matched
                if (t.id, label_id) in self.label_repo._task_labels
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
            total_pages=(total + pagination.limit - 1) // pagination.limit if pagination.limit > 0 else 0,
        )

    async def delete(self, record_id: int) -> bool:
        if record_id in self._tasks:
            del self._tasks[record_id]
            return True
        return False


class InMemoryProjectRepoForDay7(ProjectRepository):
    """In-memory project repository with workspace role lookup."""

    def __init__(
        self,
        session: Any,
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


class Day7TestContext:
    """Encapsulates test repositories, fake redis, services, and actor accounts."""

    def __init__(self) -> None:
        self.session = cast(Any, FakeAsyncSession())
        self.fake_redis = FakeRedis()
        self.cache_service = CacheService(cast(Redis, self.fake_redis))

        self.user_repo = InMemoryUserRepository(self.session)
        self.member_repo = InMemoryWorkspaceMemberRepository(self.session, self.user_repo)
        self.workspace_repo = InMemoryWorkspaceRepository(self.session, self.member_repo)
        self.project_repo = InMemoryProjectRepoForDay7(
            self.session, self.workspace_repo, self.member_repo
        )
        self.label_repo = InMemoryLabelRepoForDay7(self.session, self.project_repo)
        self.task_repo = InMemoryTaskRepoForDay7(
            self.session, self.project_repo, self.user_repo, self.label_repo
        )

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
            cache_service=self.cache_service,
        )
        self.label_service = LabelService(
            session=self.session,
            label_repo=self.label_repo,
            project_repo=self.project_repo,
            task_repo=self.task_repo,
            workspace_repo=self.workspace_repo,
            member_repo=self.member_repo,
            cache_service=self.cache_service,
        )

        self.owner = self.user_repo.add_test_user(1, "owner@example.com")
        self.editor = self.user_repo.add_test_user(2, "editor@example.com")
        self.member = self.user_repo.add_test_user(3, "member@example.com")


@pytest.fixture
def day7_ctx() -> Generator[Day7TestContext, None, None]:
    """Wire Day 7 repositories and cache service into dependency overrides."""
    ctx = Day7TestContext()
    app.dependency_overrides[get_db] = lambda: ctx.session
    app.dependency_overrides[get_cache_service] = lambda: ctx.cache_service
    app.dependency_overrides[get_user_repository] = lambda: ctx.user_repo
    app.dependency_overrides[get_workspace_repository] = lambda: ctx.workspace_repo
    app.dependency_overrides[get_workspace_member_repository] = lambda: ctx.member_repo
    app.dependency_overrides[get_project_repository] = lambda: ctx.project_repo
    app.dependency_overrides[get_task_repository] = lambda: ctx.task_repo
    app.dependency_overrides[get_label_repository] = lambda: ctx.label_repo
    app.dependency_overrides[get_project_service] = lambda: ctx.project_service
    app.dependency_overrides[get_task_service] = lambda: ctx.task_service
    app.dependency_overrides[get_label_service] = lambda: ctx.label_service
    yield ctx
    app.dependency_overrides.clear()


async def _seed_day7_project(ctx: Day7TestContext) -> tuple[Workspace, Project]:
    """Helper creating a workspace and project with test members."""
    ws = await ctx.workspace_repo.create(name="Product Engineering", owner_id=ctx.owner.id)
    await ctx.member_repo.add_member(ws.id, ctx.owner.id, role=WorkspaceRole.OWNER)
    await ctx.member_repo.add_member(ws.id, ctx.editor.id, role=WorkspaceRole.EDITOR)
    await ctx.member_repo.add_member(ws.id, ctx.member.id, role=WorkspaceRole.EDITOR)

    proj = await ctx.project_repo.create(
        workspace_id=ws.id,
        name="Day 7 Roadmap",
        description="Search, filter, pagination, and caching",
        status=ProjectStatus.ACTIVE,
    )
    return ws, proj


@pytest.mark.anyio
async def test_cache_service_build_project_tasks_cache_key_deterministic() -> None:
    """Cache key generation is deterministic regardless of query parameter insertion order."""
    fake_redis = FakeRedis()
    service = CacheService(cast(Redis, fake_redis))

    params_1 = {"search": "login", "statuses": ["TODO", "IN_PROGRESS"], "limit": 20}
    params_2 = {"limit": 20, "statuses": ["TODO", "IN_PROGRESS"], "search": "login"}

    key_1 = service.build_project_tasks_cache_key(
        project_id=10, version=1, page=1, limit=20, query_parts=params_1
    )
    key_2 = service.build_project_tasks_cache_key(
        project_id=10, version=1, page=1, limit=20, query_parts=params_2
    )

    assert key_1 == key_2
    assert key_1.startswith("cache:project:10:tasks:v_1:page_1_limit_20:")

    params_different = {"search": "logout", "limit": 20}
    key_different = service.build_project_tasks_cache_key(
        project_id=10, version=1, page=1, limit=20, query_parts=params_different
    )
    assert key_1 != key_different


@pytest.mark.anyio
async def test_cache_service_versioning_and_crud() -> None:
    """Verify version bumping and get/set/delete in CacheService."""
    fake_redis = FakeRedis()
    service = CacheService(cast(Redis, fake_redis))

    initial_version = await service.get_project_tasks_version(10)
    assert initial_version == 1

    next_version = await service.bump_project_tasks_version(10)
    assert next_version == 2
    assert await service.get_project_tasks_version(10) == 2

    miss = await service.get("missing_key")
    assert miss is None

    payload = {"items": [{"id": 1, "title": "Test Task"}], "total": 1}
    success = await service.set("cache:project:1:tasks:sample", payload, ttl=60)
    assert success is True

    cached = await service.get("cache:project:1:tasks:sample")
    assert cached == payload

    deleted = await service.delete("cache:project:1:tasks:sample")
    assert deleted is True
    assert await service.get("cache:project:1:tasks:sample") is None


@pytest.mark.anyio
async def test_cache_service_resilience_on_redis_errors() -> None:
    """CacheService swallows RedisErrors gracefully without raising exceptions."""
    fake_redis = FakeRedis()
    fake_redis.simulate_error = True
    service = CacheService(cast(Redis, fake_redis))

    assert await service.get("key") is None
    assert await service.set("key", {"a": 1}) is False
    assert await service.delete("key") is False
    assert await service.invalidate_pattern("cache:*") == 0
    assert await service.get_project_tasks_version(1) == 1
    assert await service.bump_project_tasks_version(1) == 1


@pytest.mark.anyio
async def test_search_by_title_and_description(
    day7_ctx: Day7TestContext,
    client: httpx.AsyncClient,
) -> None:
    """Search matches case-insensitively on task title and description."""
    _, proj = await _seed_day7_project(day7_ctx)
    app.dependency_overrides[get_current_user] = lambda: day7_ctx.owner

    await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="Implement OAuth2 Login",
        description="Support Google and GitHub SSO",
    )
    await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="Setup Redis Cache",
        description="Speed up list endpoints with query hash caching",
    )
    await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="Database Migration",
        description="Add composite index on status and priority",
    )

    resp_title = await client.get(f"/api/v1/projects/{proj.id}/tasks?search=oauth2")
    assert resp_title.status_code == 200
    data_title = resp_title.json()
    assert data_title["total"] == 1
    assert data_title["items"][0]["title"] == "Implement OAuth2 Login"

    resp_desc = await client.get(f"/api/v1/projects/{proj.id}/tasks?search=SPEED UP")
    assert resp_desc.status_code == 200
    data_desc = resp_desc.json()
    assert data_desc["total"] == 1
    assert data_desc["items"][0]["title"] == "Setup Redis Cache"

    resp_none = await client.get(f"/api/v1/projects/{proj.id}/tasks?search=nonexistent_token")
    assert resp_none.status_code == 200
    assert resp_none.json()["total"] == 0


@pytest.mark.anyio
async def test_search_strips_whitespace_only_query(
    day7_ctx: Day7TestContext,
    client: httpx.AsyncClient,
) -> None:
    """Whitespace-only search query is stripped to None, returning unconstrained tasks."""
    _, proj = await _seed_day7_project(day7_ctx)
    app.dependency_overrides[get_current_user] = lambda: day7_ctx.owner

    await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="First Task",
    )
    await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="Second Task",
    )

    resp = await client.get(f"/api/v1/projects/{proj.id}/tasks?search=%20%20%20")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


@pytest.mark.anyio
async def test_filtering_by_multi_status_and_priority(
    day7_ctx: Day7TestContext,
    client: httpx.AsyncClient,
) -> None:
    """Filter by multiple statuses and priorities simultaneously."""
    _, proj = await _seed_day7_project(day7_ctx)
    app.dependency_overrides[get_current_user] = lambda: day7_ctx.owner

    t1 = await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="Task 1",
        priority=TaskPriority.LOW,
    )
    t1.status = TaskStatus.TODO

    t2 = await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="Task 2",
        priority=TaskPriority.HIGH,
    )
    t2.status = TaskStatus.IN_PROGRESS

    t3 = await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="Task 3",
        priority=TaskPriority.URGENT,
    )
    t3.status = TaskStatus.DONE

    resp = await client.get(
        f"/api/v1/projects/{proj.id}/tasks?status=TODO&status=IN_PROGRESS&priority=HIGH"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Task 2"

    resp_multi_prio = await client.get(
        f"/api/v1/projects/{proj.id}/tasks?priority=HIGH&priority=URGENT"
    )
    assert resp_multi_prio.status_code == 200
    assert resp_multi_prio.json()["total"] == 2


@pytest.mark.anyio
async def test_filtering_by_due_date_range(
    day7_ctx: Day7TestContext,
    client: httpx.AsyncClient,
) -> None:
    """Filter tasks by due date range (due_date_from, due_date_to)."""
    _, proj = await _seed_day7_project(day7_ctx)
    app.dependency_overrides[get_current_user] = lambda: day7_ctx.owner

    base_time = datetime(2026, 6, 1, 12, 0, 0)
    await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="Early Task",
        due_date=base_time,
    )
    await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="Mid Task",
        due_date=base_time + timedelta(days=5),
    )
    await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="Late Task",
        due_date=base_time + timedelta(days=10),
    )

    from_str = "2026-06-03T00:00:00Z"
    to_str = "2026-06-08T00:00:00Z"
    resp = await client.get(
        f"/api/v1/projects/{proj.id}/tasks?due_date_from={from_str}&due_date_to={to_str}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Mid Task"


@pytest.mark.anyio
async def test_filter_due_date_from_after_to_returns_400(
    day7_ctx: Day7TestContext,
    client: httpx.AsyncClient,
) -> None:
    """Passing due_date_from greater than due_date_to returns 400 Bad Request."""
    _, proj = await _seed_day7_project(day7_ctx)
    app.dependency_overrides[get_current_user] = lambda: day7_ctx.owner

    resp = await client.get(
        f"/api/v1/projects/{proj.id}/tasks?due_date_from=2026-06-10T00:00:00Z&due_date_to=2026-06-01T00:00:00Z"
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == ERROR_INVALID_DATE_RANGE


@pytest.mark.anyio
async def test_filtering_by_label_id(
    day7_ctx: Day7TestContext,
    client: httpx.AsyncClient,
) -> None:
    """Filter tasks attached to a specific label."""
    _, proj = await _seed_day7_project(day7_ctx)
    app.dependency_overrides[get_current_user] = lambda: day7_ctx.owner

    label_bug = await day7_ctx.label_repo.create_label(proj.id, "Bug", "#EF4444")
    label_feature = await day7_ctx.label_repo.create_label(proj.id, "Feature", "#10B981")

    t1 = await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="Fix memory leak",
    )
    t2 = await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="Build dark mode",
    )
    await day7_ctx.label_repo.assign_to_task(t1.id, label_bug.id)
    await day7_ctx.label_repo.assign_to_task(t2.id, label_feature.id)

    resp = await client.get(f"/api/v1/projects/{proj.id}/tasks?label_id={label_bug.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Fix memory leak"


@pytest.mark.anyio
async def test_sorting_by_priority(
    day7_ctx: Day7TestContext,
    client: httpx.AsyncClient,
) -> None:
    """Priority sorting respects LOW (1) -> MEDIUM (2) -> HIGH (3) -> URGENT (4)."""
    _, proj = await _seed_day7_project(day7_ctx)
    app.dependency_overrides[get_current_user] = lambda: day7_ctx.owner

    await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="Low Prio",
        priority=TaskPriority.LOW,
    )
    await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="Urgent Prio",
        priority=TaskPriority.URGENT,
    )
    await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="High Prio",
        priority=TaskPriority.HIGH,
    )

    resp_desc = await client.get(
        f"/api/v1/projects/{proj.id}/tasks?sort_by=priority&sort_order=desc"
    )
    assert resp_desc.status_code == 200
    items_desc = resp_desc.json()["items"]
    assert [t["priority"] for t in items_desc] == ["URGENT", "HIGH", "LOW"]

    resp_asc = await client.get(
        f"/api/v1/projects/{proj.id}/tasks?sort_by=priority&sort_order=asc"
    )
    assert resp_asc.status_code == 200
    items_asc = resp_asc.json()["items"]
    assert [t["priority"] for t in items_asc] == ["LOW", "HIGH", "URGENT"]


@pytest.mark.anyio
async def test_sorting_by_title_and_due_date(
    day7_ctx: Day7TestContext,
    client: httpx.AsyncClient,
) -> None:
    """Verify title sorting and due_date sorting (nulls placed last in both directions)."""
    _, proj = await _seed_day7_project(day7_ctx)
    app.dependency_overrides[get_current_user] = lambda: day7_ctx.owner

    t_b = await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="Beta Task",
        due_date=datetime(2026, 7, 20),
    )
    t_a = await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="Alpha Task",
        due_date=datetime(2026, 7, 10),
    )
    t_none = await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="Zeta Task",
        due_date=None,
    )

    resp_title_asc = await client.get(
        f"/api/v1/projects/{proj.id}/tasks?sort_by=title&sort_order=asc"
    )
    assert resp_title_asc.status_code == 200
    titles_asc = [t["title"] for t in resp_title_asc.json()["items"]]
    assert titles_asc == ["Alpha Task", "Beta Task", "Zeta Task"]

    resp_date_asc = await client.get(
        f"/api/v1/projects/{proj.id}/tasks?sort_by=due_date&sort_order=asc"
    )
    assert resp_date_asc.status_code == 200
    dates_asc_ids = [t["id"] for t in resp_date_asc.json()["items"]]
    assert dates_asc_ids == [t_a.id, t_b.id, t_none.id]


@pytest.mark.anyio
async def test_pagination_mechanics(
    day7_ctx: Day7TestContext,
    client: httpx.AsyncClient,
) -> None:
    """Pagination splits tasks across pages with correct metadata."""
    _, proj = await _seed_day7_project(day7_ctx)
    app.dependency_overrides[get_current_user] = lambda: day7_ctx.owner

    for i in range(5):
        await day7_ctx.task_repo.create_task(
            project_id=proj.id,
            created_by=day7_ctx.owner.id,
            title=f"Paged Task {i + 1}",
        )

    resp_p1 = await client.get(f"/api/v1/projects/{proj.id}/tasks?page=1&limit=2")
    assert resp_p1.status_code == 200
    d1 = resp_p1.json()
    assert d1["page"] == 1
    assert d1["limit"] == 2
    assert d1["total"] == 5
    assert d1["total_pages"] == 3
    assert len(d1["items"]) == 2

    resp_p3 = await client.get(f"/api/v1/projects/{proj.id}/tasks?page=3&limit=2")
    assert resp_p3.status_code == 200
    d3 = resp_p3.json()
    assert d3["page"] == 3
    assert len(d3["items"]) == 1

    resp_p4 = await client.get(f"/api/v1/projects/{proj.id}/tasks?page=4&limit=2")
    assert resp_p4.status_code == 200
    assert len(resp_p4.json()["items"]) == 0


@pytest.mark.anyio
async def test_redis_cache_hit_and_version_invalidation(
    day7_ctx: Day7TestContext,
    client: httpx.AsyncClient,
) -> None:
    """First request misses cache, second hits cache; mutations bump version preventing stale reads."""
    _, proj = await _seed_day7_project(day7_ctx)
    app.dependency_overrides[get_current_user] = lambda: day7_ctx.owner

    t1 = await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="Cached Task 1",
    )

    assert day7_ctx.task_repo.list_call_count == 0
    assert await day7_ctx.cache_service.get_project_tasks_version(proj.id) == 1

    resp_1 = await client.get(f"/api/v1/projects/{proj.id}/tasks?page=1&limit=10")
    assert resp_1.status_code == 200
    assert day7_ctx.task_repo.list_call_count == 1

    resp_2 = await client.get(f"/api/v1/projects/{proj.id}/tasks?page=1&limit=10")
    assert resp_2.status_code == 200
    assert day7_ctx.task_repo.list_call_count == 1

    create_resp = await client.post(
        f"/api/v1/projects/{proj.id}/tasks",
        json={"title": "New Task Invalidation Trigger"},
    )
    assert create_resp.status_code == 201
    assert await day7_ctx.cache_service.get_project_tasks_version(proj.id) == 2

    resp_3 = await client.get(f"/api/v1/projects/{proj.id}/tasks?page=1&limit=10")
    assert resp_3.status_code == 200
    assert day7_ctx.task_repo.list_call_count == 2
    assert resp_3.json()["total"] == 2

    patch_resp = await client.patch(
        f"/api/v1/tasks/{t1.id}",
        json={"title": "Updated Task Title"},
    )
    assert patch_resp.status_code == 200
    assert await day7_ctx.cache_service.get_project_tasks_version(proj.id) == 3

    status_resp = await client.patch(
        f"/api/v1/tasks/{t1.id}/status",
        json={"status": "IN_PROGRESS"},
    )
    assert status_resp.status_code == 200
    assert await day7_ctx.cache_service.get_project_tasks_version(proj.id) == 4

    del_resp = await client.delete(f"/api/v1/tasks/{t1.id}")
    assert del_resp.status_code == 200
    assert await day7_ctx.cache_service.get_project_tasks_version(proj.id) == 5


@pytest.mark.anyio
async def test_label_mutation_and_deletion_invalidates_task_cache(
    day7_ctx: Day7TestContext,
    client: httpx.AsyncClient,
) -> None:
    """Attaching, detaching, and deleting labels increments project version."""
    _, proj = await _seed_day7_project(day7_ctx)
    app.dependency_overrides[get_current_user] = lambda: day7_ctx.owner

    lbl = await day7_ctx.label_repo.create_label(proj.id, "Frontend", "#3B82F6")
    t1 = await day7_ctx.task_repo.create_task(
        project_id=proj.id,
        created_by=day7_ctx.owner.id,
        title="Button alignment",
    )

    initial_ver = await day7_ctx.cache_service.get_project_tasks_version(proj.id)

    assign_resp = await client.post(f"/api/v1/tasks/{t1.id}/labels/{lbl.id}")
    assert assign_resp.status_code == 200
    ver_after_assign = await day7_ctx.cache_service.get_project_tasks_version(proj.id)
    assert ver_after_assign == initial_ver + 1

    detach_resp = await client.delete(f"/api/v1/tasks/{t1.id}/labels/{lbl.id}")
    assert detach_resp.status_code == 200
    ver_after_detach = await day7_ctx.cache_service.get_project_tasks_version(proj.id)
    assert ver_after_detach == ver_after_assign + 1

    delete_label_resp = await client.delete(f"/api/v1/labels/{lbl.id}")
    assert delete_label_resp.status_code == 200
    ver_after_delete = await day7_ctx.cache_service.get_project_tasks_version(proj.id)
    assert ver_after_delete == ver_after_detach + 1


@pytest.mark.anyio
async def test_real_task_repository_sql_compilation_with_mysql_dialect() -> None:
    """Verify that TaskRepository compiles exact MySQL SQL statements for filtering, searching, and sorting."""
    fake_session = FakeAsyncSession()
    repo = TaskRepository(cast(Any, fake_session))

    _, date_asc_query = repo.build_list_queries(
        project_id=1,
        pagination=PaginationParams(page=1, limit=10),
        sort_by=TaskSortBy.DUE_DATE,
        sort_order=SortOrder.ASC,
    )
    sql_date_asc = str(date_asc_query.compile(dialect=mysql.dialect()))
    assert "ORDER BY tasks.due_date IS NULL ASC, tasks.due_date ASC, tasks.id ASC" in sql_date_asc

    _, date_desc_query = repo.build_list_queries(
        project_id=1,
        pagination=PaginationParams(page=1, limit=10),
        sort_by=TaskSortBy.DUE_DATE,
        sort_order=SortOrder.DESC,
    )
    sql_date_desc = str(date_desc_query.compile(dialect=mysql.dialect()))
    assert "ORDER BY tasks.due_date IS NULL ASC, tasks.due_date DESC, tasks.id DESC" in sql_date_desc

    _, search_query = repo.build_list_queries(
        project_id=1,
        pagination=PaginationParams(page=1, limit=10),
        search="special%_keyword",
    )
    sql_search = str(search_query.compile(dialect=mysql.dialect()))
    assert "ESCAPE '/'" in sql_search

    _, full_filter_query = repo.build_list_queries(
        project_id=1,
        pagination=PaginationParams(page=1, limit=10),
        statuses=[TaskStatus.TODO, TaskStatus.IN_PROGRESS],
        priorities=[TaskPriority.HIGH, TaskPriority.URGENT],
        assignee_id=99,
        due_date_from=datetime(2026, 1, 1),
        due_date_to=datetime(2026, 12, 31),
        label_id=7,
        sort_by=TaskSortBy.PRIORITY,
        sort_order=SortOrder.DESC,
    )
    sql_full = str(full_filter_query.compile(dialect=mysql.dialect()))
    assert "tasks.status IN" in sql_full
    assert "tasks.priority IN" in sql_full
    assert "tasks.assignee_id =" in sql_full
    assert "tasks.due_date >=" in sql_full
    assert "tasks.due_date <=" in sql_full
    assert "tasks.id IN (SELECT task_labels.task_id" in sql_full
    assert "CASE WHEN (tasks.priority =" in sql_full
