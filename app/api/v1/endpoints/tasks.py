"""Task API endpoints for task creation, listing, status transitions, and deletion."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query, status

from app.core.constants import MAX_SEARCH_KEYWORD_LENGTH
from app.core.dependencies import CurrentUser, PaginationDep, TaskServiceDep
from app.core.messages import SUCCESS_TASK_DELETED
from app.models.enums import SortOrder, TaskPriority, TaskSortBy, TaskStatus
from app.schemas.common import ErrorResponse, MessageResponse, PaginatedResponse
from app.schemas.task import TaskCreate, TaskResponse, TaskStatusUpdate, TaskUpdate

router = APIRouter(tags=["Tasks"])


@router.post(
    "/projects/{project_id}/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a task",
    description="Create a task inside a project. Default status is TODO. Assignee must be a workspace member.",
    responses={
        400: {"model": ErrorResponse, "description": "Bad request (assignee not in workspace)"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "Project not found"},
        409: {"model": ErrorResponse, "description": "Project is archived"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def create_task(
    project_id: int,
    data: TaskCreate,
    current_user: CurrentUser,
    service: TaskServiceDep,
    background_tasks: BackgroundTasks,
) -> TaskResponse:
    """Create task in project and schedule notification in background."""
    return await service.create_task(
        project_id=project_id,
        current_user=current_user,
        data=data,
        background_tasks=background_tasks,
    )


@router.get(
    "/projects/{project_id}/tasks",
    response_model=PaginatedResponse[TaskResponse],
    status_code=status.HTTP_200_OK,
    summary="List project tasks",
    description="Retrieve paginated tasks for a project with optional search, filtering, and sorting.",
    responses={
        400: {"model": ErrorResponse, "description": "Bad request (invalid filter parameters)"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Project not found"},
    },
)
async def list_project_tasks(
    project_id: int,
    pagination: PaginationDep,
    current_user: CurrentUser,
    service: TaskServiceDep,
    search: Annotated[
        str | None,
        Query(
            max_length=MAX_SEARCH_KEYWORD_LENGTH,
            description="Search keyword in task title or description",
        ),
    ] = None,
    statuses: Annotated[
        list[TaskStatus] | None,
        Query(alias="status", description="Filter by one or more statuses"),
    ] = None,
    priorities: Annotated[
        list[TaskPriority] | None,
        Query(alias="priority", description="Filter by one or more priorities"),
    ] = None,
    assignee_id: Annotated[
        int | None,
        Query(ge=1, description="Filter by assignee user ID"),
    ] = None,
    due_date_from: Annotated[
        datetime | None,
        Query(description="Filter tasks with due date on or after this timestamp"),
    ] = None,
    due_date_to: Annotated[
        datetime | None,
        Query(description="Filter tasks with due date on or before this timestamp"),
    ] = None,
    label_id: Annotated[
        int | None,
        Query(ge=1, description="Filter tasks attached to label ID"),
    ] = None,
    sort_by: Annotated[
        TaskSortBy,
        Query(description="Field to sort tasks by"),
    ] = TaskSortBy.CREATED_AT,
    sort_order: Annotated[
        SortOrder,
        Query(description="Sort direction (asc or desc)"),
    ] = SortOrder.DESC,
) -> PaginatedResponse[TaskResponse]:
    """List tasks in project with search, filters, sorting, and pagination."""
    return await service.list_tasks(
        project_id=project_id,
        current_user=current_user,
        pagination=pagination,
        search=search,
        statuses=statuses,
        priorities=priorities,
        assignee_id=assignee_id,
        due_date_from=due_date_from,
        due_date_to=due_date_to,
        label_id=label_id,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get(
    "/tasks/{task_id}",
    response_model=TaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Get task details",
    description="Fetch single task details ensuring caller has membership across task -> project -> workspace.",
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Task not found"},
    },
)
async def get_task(
    task_id: int,
    current_user: CurrentUser,
    service: TaskServiceDep,
) -> TaskResponse:
    """Get task by ID."""
    return await service.get_task(task_id=task_id, current_user=current_user)


@router.patch(
    "/tasks/{task_id}",
    response_model=TaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Update task",
    description="Update task fields. Blocked if parent project is archived. Assignee must be in workspace.",
    responses={
        400: {"model": ErrorResponse, "description": "Bad request (assignee not in workspace)"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "Task not found"},
        409: {"model": ErrorResponse, "description": "Project is archived"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def update_task(
    task_id: int,
    data: TaskUpdate,
    current_user: CurrentUser,
    service: TaskServiceDep,
    background_tasks: BackgroundTasks,
) -> TaskResponse:
    """Update task details and schedule assignment notification if assignee changed."""
    return await service.update_task(
        task_id=task_id,
        current_user=current_user,
        data=data,
        background_tasks=background_tasks,
    )


@router.patch(
    "/tasks/{task_id}/status",
    response_model=TaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Update task status",
    description="Fast status transition. Blocked if parent project is archived.",
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "Task not found"},
        409: {"model": ErrorResponse, "description": "Project is archived"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def update_task_status(
    task_id: int,
    data: TaskStatusUpdate,
    current_user: CurrentUser,
    service: TaskServiceDep,
    background_tasks: BackgroundTasks,
) -> TaskResponse:
    """Update task status and schedule notification in background."""
    return await service.update_task_status(
        task_id=task_id,
        current_user=current_user,
        data=data,
        background_tasks=background_tasks,
    )


@router.delete(
    "/tasks/{task_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete task",
    description="Delete task. Requires write role in parent workspace and active project.",
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "Task not found"},
        409: {"model": ErrorResponse, "description": "Project is archived"},
    },
)
async def delete_task(
    task_id: int,
    current_user: CurrentUser,
    service: TaskServiceDep,
) -> MessageResponse:
    """Delete task."""
    await service.delete_task(task_id=task_id, current_user=current_user)
    return MessageResponse(message=SUCCESS_TASK_DELETED)
