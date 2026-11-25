"""Tests for notification service, background tasks, and OpenAPI documentation."""

from collections.abc import Generator

import httpx
import pytest
from fastapi import BackgroundTasks

from app.core.dependencies import (
    get_current_user,
    get_notification_service,
    get_task_service,
)
from app.main import app
from app.models.enums import TaskPriority, TaskStatus, WorkspaceRole
from app.models.project import Project
from app.models.workspace import Workspace
from app.schemas.task import TaskCreate, TaskStatusUpdate, TaskUpdate
from app.services.notification import NotificationService
from tests.test_tasks import TaskTestContext


@pytest.fixture
def anyio_backend() -> str:
    """Run tests on asyncio backend."""
    return "asyncio"


@pytest.fixture
def notification_service() -> NotificationService:
    """Provide a fresh notification service instance."""
    return NotificationService()


@pytest.fixture
def test_ctx(notification_service: NotificationService) -> Generator[TaskTestContext, None, None]:
    """Provide a wired test context with a custom notification service."""
    ctx = TaskTestContext()
    ctx.task_service.notification_service = notification_service
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
async def test_notification_service_send_assignment(
    notification_service: NotificationService,
) -> None:
    """Verify dispatching a task assignment notification records correct payload."""
    await notification_service.send_task_assignment_notification(
        assignee_email="assignee@example.com",
        assignee_name="Alice Assignee",
        task_title="Build Background Tasks",
        project_name="Core Engine",
        assigner_name="Bob Assigner",
    )

    dispatched = notification_service.dispatched_notifications
    assert len(dispatched) == 1
    item = dispatched[0]
    assert item["type"] == "task_assigned"
    assert item["to"] == "assignee@example.com"
    assert item["assignee_name"] == "Alice Assignee"
    assert item["task_title"] == "Build Background Tasks"
    assert item["project_name"] == "Core Engine"
    assert item["assigner_name"] == "Bob Assigner"


@pytest.mark.anyio
async def test_notification_service_send_status_changed(
    notification_service: NotificationService,
) -> None:
    """Verify dispatching a status transition notification records all recipient emails."""
    await notification_service.send_task_status_changed_notification(
        recipient_emails=["creator@example.com", "assignee@example.com"],
        task_title="Deploy Container",
        project_name="Infra",
        old_status=TaskStatus.IN_PROGRESS,
        new_status=TaskStatus.DONE,
        updater_name="Charlie Lead",
    )

    dispatched = notification_service.dispatched_notifications
    assert len(dispatched) == 1
    item = dispatched[0]
    assert item["type"] == "task_status_changed"
    assert item["recipients"] == ["creator@example.com", "assignee@example.com"]
    assert item["task_title"] == "Deploy Container"
    assert item["project_name"] == "Infra"
    assert item["old_status"] == TaskStatus.IN_PROGRESS.value
    assert item["new_status"] == TaskStatus.DONE.value
    assert item["updater_name"] == "Charlie Lead"


def test_notification_service_clear(
    notification_service: NotificationService,
) -> None:
    """Verify clearing dispatched notification list."""
    notification_service.dispatched_notifications.append({"type": "test"})
    assert len(notification_service.dispatched_notifications) == 1
    notification_service.clear()
    assert len(notification_service.dispatched_notifications) == 0


@pytest.mark.anyio
async def test_task_service_create_task_enqueues_background_notification(
    test_ctx: TaskTestContext,
    notification_service: NotificationService,
) -> None:
    """Verify creating a task with an assignee schedules an assignment notification in BackgroundTasks."""
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
    assert len(notification_service.dispatched_notifications) == 0

    await bg()

    assert len(notification_service.dispatched_notifications) == 1
    notif = notification_service.dispatched_notifications[0]
    assert notif["type"] == "task_assigned"
    assert notif["to"] == test_ctx.editor.email
    assert notif["task_title"] == "Assigned Task"
    assert notif["project_name"] == project.name
    assert notif["assigner_name"] == test_ctx.owner.full_name


@pytest.mark.anyio
async def test_task_service_create_task_unassigned_no_notification(
    test_ctx: TaskTestContext,
    notification_service: NotificationService,
) -> None:
    """Verify creating a task without assignee does not enqueue an assignment notification."""
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
    assert len(notification_service.dispatched_notifications) == 0


@pytest.mark.anyio
async def test_task_service_update_task_assignee_enqueues_notification(
    test_ctx: TaskTestContext,
    notification_service: NotificationService,
) -> None:
    """Verify changing assignee during task update schedules an assignment notification."""
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
    assert len(notification_service.dispatched_notifications) == 1
    assert notification_service.dispatched_notifications[0]["to"] == test_ctx.editor.email


@pytest.mark.anyio
async def test_task_service_update_status_enqueues_notification(
    test_ctx: TaskTestContext,
    notification_service: NotificationService,
) -> None:
    """Verify transitioning task status dispatches notification to both creator and assignee."""
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
    assert len(notification_service.dispatched_notifications) == 1
    notif = notification_service.dispatched_notifications[0]
    assert notif["type"] == "task_status_changed"
    assert test_ctx.owner.email in notif["recipients"]
    assert test_ctx.editor.email in notif["recipients"]
    assert notif["old_status"] == TaskStatus.TODO.value
    assert notif["new_status"] == TaskStatus.DONE.value


def test_openapi_documentation_metadata_and_security() -> None:
    """Verify generated OpenAPI schema matches Day 8 documentation requirements."""
    schema = app.openapi()

    assert schema["info"]["title"] == "TaskHub"
    assert schema["info"]["version"] == "1.0.0"
    assert "TaskHub" in schema["info"]["description"]
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
    notification_service: NotificationService,
) -> None:
    """Verify HTTP API endpoint enqueues and completes background notification upon response."""
    _, project = await _seed_project(test_ctx)

    app.dependency_overrides[get_current_user] = lambda: test_ctx.owner
    app.dependency_overrides[get_task_service] = lambda: test_ctx.task_service
    app.dependency_overrides[get_notification_service] = lambda: notification_service

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
            assert len(notification_service.dispatched_notifications) == 1
            assert (
                notification_service.dispatched_notifications[0]["to"]
                == test_ctx.editor.email
            )
    finally:
        app.dependency_overrides.clear()
