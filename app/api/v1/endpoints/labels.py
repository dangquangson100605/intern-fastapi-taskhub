"""Label API endpoints for creating, listing, assigning, and detaching labels."""

from fastapi import APIRouter, status

from app.core.dependencies import CurrentUser, LabelServiceDep, PaginationDep
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.label import LabelCreate, LabelResponse, LabelUpdate

router = APIRouter(tags=["Labels"])


@router.post(
    "/projects/{project_id}/labels",
    response_model=LabelResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a label in a project",
    description="Create a label with a name and HEX color. Requires write role (OWNER, EDITOR).",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Project not found"},
        409: {"description": "Project is archived or label name exists in project"},
        422: {"description": "Validation error (invalid color or name length)"},
    },
)
async def create_project_label(
    project_id: int,
    data: LabelCreate,
    current_user: CurrentUser,
    service: LabelServiceDep,
) -> LabelResponse:
    """Create a label inside a project."""
    return await service.create_label(
        project_id=project_id,
        current_user=current_user,
        data=data,
    )


@router.get(
    "/projects/{project_id}/labels",
    response_model=PaginatedResponse[LabelResponse],
    status_code=status.HTTP_200_OK,
    summary="List labels in a project",
    description="Retrieve paginated labels created in a project. Accessible to all workspace members.",
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "Project not found"},
    },
)
async def list_project_labels(
    project_id: int,
    current_user: CurrentUser,
    service: LabelServiceDep,
    pagination: PaginationDep,
) -> PaginatedResponse[LabelResponse]:
    """List all labels belonging to a project."""
    return await service.list_project_labels(
        project_id=project_id,
        current_user=current_user,
        pagination=pagination,
    )


@router.get(
    "/workspaces/{workspace_id}/labels",
    response_model=PaginatedResponse[LabelResponse],
    status_code=status.HTTP_200_OK,
    summary="List labels in a workspace",
    description="Retrieve paginated labels across all projects in a workspace. Accessible to all members.",
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "Workspace not found"},
    },
)
async def list_workspace_labels(
    workspace_id: int,
    current_user: CurrentUser,
    service: LabelServiceDep,
    pagination: PaginationDep,
) -> PaginatedResponse[LabelResponse]:
    """List all labels in a workspace."""
    return await service.list_workspace_labels(
        workspace_id=workspace_id,
        current_user=current_user,
        pagination=pagination,
    )


@router.patch(
    "/labels/{label_id}",
    response_model=LabelResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a label",
    description="Update a label name or HEX color. Requires write role (OWNER, EDITOR).",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Label not found"},
        409: {"description": "Project is archived or label name exists in project"},
        422: {"description": "Validation error"},
    },
)
async def update_label(
    label_id: int,
    data: LabelUpdate,
    current_user: CurrentUser,
    service: LabelServiceDep,
) -> LabelResponse:
    """Update label details."""
    return await service.update_label(
        label_id=label_id,
        current_user=current_user,
        data=data,
    )


@router.delete(
    "/labels/{label_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete a label",
    description="Delete a label and automatically remove it from all associated tasks.",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Label not found"},
        409: {"description": "Project is archived"},
    },
)
async def delete_label(
    label_id: int,
    current_user: CurrentUser,
    service: LabelServiceDep,
) -> MessageResponse:
    """Delete a label."""
    return await service.delete_label(
        label_id=label_id,
        current_user=current_user,
    )


@router.post(
    "/tasks/{task_id}/labels/{label_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign a label to a task",
    description="Attach a label to a task. Enforces same-project scope and prevents duplicate assignment.",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Task or label not found"},
        409: {"description": "Label already assigned or project archived"},
    },
)
async def assign_label_to_task(
    task_id: int,
    label_id: int,
    current_user: CurrentUser,
    service: LabelServiceDep,
) -> MessageResponse:
    """Assign label to task."""
    return await service.assign_label_to_task(
        task_id=task_id,
        label_id=label_id,
        current_user=current_user,
    )


@router.delete(
    "/tasks/{task_id}/labels/{label_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove a label from a task",
    description="Detach a label from a task. Requires write role (OWNER, EDITOR).",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Task or label association not found"},
        409: {"description": "Project is archived"},
    },
)
async def remove_label_from_task(
    task_id: int,
    label_id: int,
    current_user: CurrentUser,
    service: LabelServiceDep,
) -> MessageResponse:
    """Remove label from task."""
    return await service.remove_label_from_task(
        task_id=task_id,
        label_id=label_id,
        current_user=current_user,
    )


@router.get(
    "/tasks/{task_id}/labels",
    response_model=list[LabelResponse],
    status_code=status.HTTP_200_OK,
    summary="List labels attached to a task",
    description="Retrieve all labels currently associated with a task.",
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "Task not found"},
    },
)
async def list_task_labels(
    task_id: int,
    current_user: CurrentUser,
    service: LabelServiceDep,
) -> list[LabelResponse]:
    """List labels attached to task."""
    return await service.list_task_labels(
        task_id=task_id,
        current_user=current_user,
    )
