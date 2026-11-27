"""Tests for notification service, background tasks, and OpenAPI documentation."""

from collections.abc import Generator
from typing import Any

import httpx
import pytest
from fastapi import BackgroundTasks

from app.core.dependencies import get_current_user, get_task_service
from app.main import app
from app.models.enums import TaskPriority, TaskStatus, WorkspaceRole
from app.models.project import Project
from app.models.workspace import Workspace
from app.schemas.task import TaskCreate, TaskStatusUpdate, TaskUpdate
from app.services.notification import NotificationService
from tests.test_tasks import TaskTestContext


class FakeNotificationService(NotificationService):
    """Test fake capturing dispatched notification payloads without memory leaks."""

    def __init__(self) -> None:
        self.dispatched_assignments: list[dict[str, Any]] = []
        self.dispatched_status_changes: list[dict[str, Any]] = []

    async def send_task_assignment_notification(
        self,
        task_id: int,
        project_id: int,
        assignee_id: int,
        assigner_id: int,
        assignee_email: str,
        task_title: str,
        project_name: str,
        assigner_name: str,
    ) -> None:
        self.dispatched_assignments.append(
            {
                "task_id": task_id,
                "project_id": project_id,
                "assignee_id": assignee_id,
                "assigner_id": assigner_id,
                "assignee_email": assignee_email,
                "task_title": task_title,
                "project_name": project_name,
                "assigner_name": assigner_name,
            }
        )

    async def send_task_status_changed_notification(
        self,
        task_id: int,
        project_id: int,
        old_status: TaskStatus,
        new_status: TaskStatus,
        updater_id: int,
        recipient_emails: list[str],
        task_title: str,
        project_name: str,
        updater_name: str,
    ) -> None:
        self.dispatched_status_changes.append(
            {
                "task_id": task_id,
                "project_id": project_id,
                "old_status": old_status,
                "new_status": new_status,
                "updater_id": updater_id,
                "recipient_emails": recipient_emails,
                "task_title": task_title,
                "project_name": project_name,
                "updater_name": updater_name,
            }
        )


@pytest.fixture
def anyio_backend() -> str:
    """Run tests on asyncio backend."""
    return "asyncio"


@pytest.fixture
def fake_notification_service() -> FakeNotificationService:
    """Provide a fresh fake notification service instance."""
    return FakeNotificationService()


@pytest.fixture
def test_ctx(fake_notification_service: FakeNotificationService) -> Generator[TaskTestContext, None, None]:
    """Provide a wired test context with a fake notification service."""
    ctx = TaskTestContext()
    ctx.task_service.notification_service = fake_notification_service
    yield ctx


async def _seed_project(ctx: TaskTestContext) -> tuple[Workspace, Project]:
    """Helper creating a workspace and project for testing."""
    ws = await ctx.workspace_repo.create(name="Notification WS", owner_id=ctx.owner.id)
    await ctx.member_repo.add_member(ws.id, ctx.owner.id, role=WorkspaceRole.OWNER)
    await ctx.member_repo.add_member(ws.id, ctx.editor.id, role=WorkspaceRole.EDITOR)
    project = await ctx.project_repo.create(
        workspace_id=ws.id,
        name="Notification Project",
    )
    return ws, project


@pytest.mark.anyio
async def test_notification_service_send_assignment_no_memory_leak() -> None:
    """Verify real NotificationService does not maintain persistent in-memory notification list."""
    service = NotificationService()
    assert not hasattr(service, "dispatched_notifications")

    await service.send_task_assignment_notification(
        task_id=1,
        project_id=1,
        assignee_id=2,
        assigner_id=1,
        assignee_email="assignee@example.com",
        task_title="Build Background Tasks",
        project_name="Core Engine",
        assigner_name="Bob Assigner",
    )
    assert not hasattr(service, "dispatched_notifications")


@pytest.mark.anyio
async def test_notification_service_send_status_changed_no_memory_leak() -> None:
    """Verify real NotificationService does not maintain persistent in-memory notification list."""
    service = NotificationService()
    await service.send_task_status_changed_notification(
        task_id=1,
        project_id=1,
        old_status=TaskStatus.IN_PROGRESS,
        new_status=TaskStatus.DONE,
        updater_id=1,
        recipient_emails=["creator@example.com", "assignee@example.com"],
        task_title="Deploy Container",
        project_name="Infra",
        updater_name="Charlie Lead",
    )
    assert not hasattr(service, "dispatched_notifications")


@pytest.mark.anyio
async def test_task_service_create_task_enqueues_background_notification(
    test_ctx: TaskTestContext,
    fake_notification_service: FakeNotificationService,
) -> None:
    """Verify creating a task assigned to another user schedules an assignment notification."""
    _, project = await _seed_project(test_ctx)

    bg = BackgroundTasks()
    task_res = await test_ctx.task_service.create_task(
        project_id=project.id,
        current_user=test_ctx.owner,
        data=TaskCreate(
            title="Assigned Task",
            description="Task to test background notification",
            priority=TaskPriority.HIGH,
            assignee_id=test_ctx.editor.id,
        ),
        background_tasks=bg,
    )

    assert task_res.title == "Assigned Task"
    assert len(fake_notification_service.dispatched_assignments) == 0

    await bg()

    assert len(fake_notification_service.dispatched_assignments) == 1
    notif = fake_notification_service.dispatched_assignments[0]
    assert notif["assignee_id"] == test_ctx.editor.id
    assert notif["assigner_id"] == test_ctx.owner.id
    assert notif["assignee_email"] == test_ctx.editor.email
    assert notif["task_title"] == "Assigned Task"
    assert notif["project_name"] == project.name


@pytest.mark.anyio
async def test_task_service_create_task_self_assign_no_notification(
    test_ctx: TaskTestContext,
    fake_notification_service: FakeNotificationService,
) -> None:
    """Negative test: assigning task to oneself does not enqueue a redundant assignment notification."""
    _, project = await _seed_project(test_ctx)

    bg = BackgroundTasks()
    await test_ctx.task_service.create_task(
        project_id=project.id,
        current_user=test_ctx.owner,
        data=TaskCreate(
            title="Self Assigned Task",
            priority=TaskPriority.MEDIUM,
            assignee_id=test_ctx.owner.id,
        ),
        background_tasks=bg,
    )

    await bg()
    assert len(fake_notification_service.dispatched_assignments) == 0


@pytest.mark.anyio
async def test_task_service_create_task_unassigned_no_notification(
    test_ctx: TaskTestContext,
    fake_notification_service: FakeNotificationService,
) -> None:
    """Negative test: creating an unassigned task does not enqueue an assignment notification."""
    _, project = await _seed_project(test_ctx)

    bg = BackgroundTasks()
    await test_ctx.task_service.create_task(
        project_id=project.id,
        current_user=test_ctx.owner,
        data=TaskCreate(
            title="Unassigned Task",
            priority=TaskPriority.LOW,
            assignee_id=None,
        ),
        background_tasks=bg,
    )

    await bg()
    assert len(fake_notification_service.dispatched_assignments) == 0


@pytest.mark.anyio
async def test_task_service_update_task_assignee_enqueues_notification(
    test_ctx: TaskTestContext,
    fake_notification_service: FakeNotificationService,
) -> None:
    """Verify changing assignee to another user during task update schedules an assignment notification."""
    _, project = await _seed_project(test_ctx)

    task = await test_ctx.task_repo.create_task(
        project_id=project.id,
        created_by=test_ctx.owner.id,
        title="Initial Task",
        priority=TaskPriority.MEDIUM,
        assignee_id=None,
    )

    bg = BackgroundTasks()
    await test_ctx.task_service.update_task(
        task_id=task.id,
        current_user=test_ctx.owner,
        data=TaskUpdate(assignee_id=test_ctx.editor.id),
        background_tasks=bg,
    )

    await bg()
    assert len(fake_notification_service.dispatched_assignments) == 1
    assert fake_notification_service.dispatched_assignments[0]["assignee_email"] == test_ctx.editor.email


@pytest.mark.anyio
async def test_task_service_update_task_same_assignee_no_notification(
    test_ctx: TaskTestContext,
    fake_notification_service: FakeNotificationService,
) -> None:
    """Negative test: updating other fields without changing assignee does not re-enqueue notification."""
    _, project = await _seed_project(test_ctx)

    task = await test_ctx.task_repo.create_task(
        project_id=project.id,
        created_by=test_ctx.owner.id,
        title="Initial Task",
        priority=TaskPriority.MEDIUM,
        assignee_id=test_ctx.editor.id,
    )

    bg = BackgroundTasks()
    await test_ctx.task_service.update_task(
        task_id=task.id,
        current_user=test_ctx.owner,
        data=TaskUpdate(title="Updated Task Title"),
        background_tasks=bg,
    )

    await bg()
    assert len(fake_notification_service.dispatched_assignments) == 0


@pytest.mark.anyio
async def test_task_service_update_task_self_assign_no_notification(
    test_ctx: TaskTestContext,
    fake_notification_service: FakeNotificationService,
) -> None:
    """Negative test: assigning a previously unassigned task to oneself does not trigger notification."""
    _, project = await _seed_project(test_ctx)

    task = await test_ctx.task_repo.create_task(
        project_id=project.id,
        created_by=test_ctx.owner.id,
        title="Initial Task",
        priority=TaskPriority.MEDIUM,
        assignee_id=None,
    )

    bg = BackgroundTasks()
    await test_ctx.task_service.update_task(
        task_id=task.id,
        current_user=test_ctx.owner,
        data=TaskUpdate(assignee_id=test_ctx.owner.id),
        background_tasks=bg,
    )

    await bg()
    assert len(fake_notification_service.dispatched_assignments) == 0


@pytest.mark.anyio
async def test_task_service_update_status_enqueues_notification_excluding_actor(
    test_ctx: TaskTestContext,
    fake_notification_service: FakeNotificationService,
) -> None:
    """Verify transitioning status notifies participants but excludes the actor who performed the transition."""
    _, project = await _seed_project(test_ctx)

    task = await test_ctx.task_repo.create_task(
        project_id=project.id,
        created_by=test_ctx.owner.id,
        title="Ready for review",
        priority=TaskPriority.HIGH,
        assignee_id=test_ctx.editor.id,
    )

    bg = BackgroundTasks()
    await test_ctx.task_service.update_task_status(
        task_id=task.id,
        current_user=test_ctx.owner,
        data=TaskStatusUpdate(status=TaskStatus.DONE),
        background_tasks=bg,
    )

    await bg()
    assert len(fake_notification_service.dispatched_status_changes) == 1
    notif = fake_notification_service.dispatched_status_changes[0]
    assert test_ctx.editor.email in notif["recipient_emails"]
    assert test_ctx.owner.email not in notif["recipient_emails"]
    assert notif["old_status"] == TaskStatus.TODO
    assert notif["new_status"] == TaskStatus.DONE


@pytest.mark.anyio
async def test_task_service_update_status_same_status_no_notification(
    test_ctx: TaskTestContext,
    fake_notification_service: FakeNotificationService,
) -> None:
    """Negative test: updating status to the same status does not enqueue a notification."""
    _, project = await _seed_project(test_ctx)

    task = await test_ctx.task_repo.create_task(
        project_id=project.id,
        created_by=test_ctx.owner.id,
        title="Ready for review",
        priority=TaskPriority.HIGH,
        assignee_id=test_ctx.editor.id,
    )

    bg = BackgroundTasks()
    await test_ctx.task_service.update_task_status(
        task_id=task.id,
        current_user=test_ctx.owner,
        data=TaskStatusUpdate(status=TaskStatus.TODO),
        background_tasks=bg,
    )

    await bg()
    assert len(fake_notification_service.dispatched_status_changes) == 0


def test_openapi_documentation_metadata_and_security() -> None:
    """Verify generated OpenAPI schema has accurate tags, security, and no spurious root responses."""
    schema = app.openapi()

    assert schema["info"]["title"] == "TaskHub"
    assert schema["info"]["version"] == "1.0.0"
    assert "contact" in schema["info"]
    assert "license" in schema["info"]

    tag_names = {t["name"] for t in schema.get("tags", [])}
    expected_tags = {
        "Auth",
        "Users",
        "Workspaces",
        "Projects",
        "Tasks",
        "Labels",
        "Comments",
    }
    assert expected_tags.issubset(tag_names)

    components = schema.get("components", {})
    security_schemes = components.get("securitySchemes", {})
    assert "HTTPBearer" in security_schemes

    health_op = schema["paths"]["/health"]["get"]
    assert "401" not in health_op["responses"]
    assert "403" not in health_op["responses"]
    assert "404" not in health_op["responses"]
    assert "409" not in health_op["responses"]

    task_create_op = schema["paths"]["/api/v1/projects/{project_id}/tasks"]["post"]
    assert "400" in task_create_op["responses"]
    assert "401" in task_create_op["responses"]
    assert "403" in task_create_op["responses"]
    assert "404" in task_create_op["responses"]
    assert "409" in task_create_op["responses"]
    assert "422" in task_create_op["responses"]


@pytest.mark.anyio
async def test_api_create_task_background_task_execution(
    test_ctx: TaskTestContext,
    fake_notification_service: FakeNotificationService,
) -> None:
    """Verify HTTP API endpoint enqueues and completes background notification upon response."""
    _, project = await _seed_project(test_ctx)

    app.dependency_overrides[get_current_user] = lambda: test_ctx.owner
    app.dependency_overrides[get_task_service] = lambda: test_ctx.task_service

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/v1/projects/{project.id}/tasks",
                json={
                    "title": "API Background Task",
                    "description": "Triggered via HTTP endpoint",
                    "priority": "HIGH",
                    "assignee_id": test_ctx.editor.id,
                },
            )
            assert resp.status_code == 201
            assert resp.json()["title"] == "API Background Task"
            assert len(fake_notification_service.dispatched_assignments) == 1
            assert (
                fake_notification_service.dispatched_assignments[0]["assignee_email"]
                == test_ctx.editor.email
            )
    finally:
        app.dependency_overrides.clear()
