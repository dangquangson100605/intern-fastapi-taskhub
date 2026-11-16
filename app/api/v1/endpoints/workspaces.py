"""Workspace and membership management endpoints."""

from fastapi import APIRouter, Query, status

from app.core.constants import DEFAULT_LIMIT, DEFAULT_PAGE, MAX_LIMIT
from app.core.dependencies import CurrentUser, WorkspaceServiceDep
from app.core.messages import SUCCESS_WORKSPACE_DELETED, SUCCESS_WORKSPACE_MEMBER_REMOVED
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceMemberAdd,
    WorkspaceMemberResponse,
    WorkspaceMemberUpdate,
    WorkspaceResponse,
    WorkspaceUpdate,
)

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


@router.post(
    "",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new workspace",
    description="Create a workspace and automatically assign the creator as OWNER.",
    responses={
        401: {"description": "Not authenticated"},
        422: {"description": "Validation error"},
    },
)
async def create_workspace(
    data: WorkspaceCreate,
    current_user: CurrentUser,
    service: WorkspaceServiceDep,
) -> WorkspaceResponse:
    """Create a new workspace."""
    return await service.create_workspace(current_user=current_user, data=data)


@router.get(
    "",
    response_model=PaginatedResponse[WorkspaceResponse],
    status_code=status.HTTP_200_OK,
    summary="List accessible workspaces",
    description="Retrieve paginated workspaces that the current user owns or belongs to.",
    responses={
        401: {"description": "Not authenticated"},
    },
)
async def list_workspaces(
    current_user: CurrentUser,
    service: WorkspaceServiceDep,
    page: int = Query(default=DEFAULT_PAGE, ge=1, description="Page number"),
    limit: int = Query(
        default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Items per page"
    ),
) -> PaginatedResponse[WorkspaceResponse]:
    """List workspaces accessible to caller."""
    return await service.list_workspaces(current_user=current_user, page=page, limit=limit)


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_200_OK,
    summary="Get workspace details",
    description="Fetch a workspace by ID if the caller is a member or system administrator.",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Workspace not found"},
    },
)
async def get_workspace(
    workspace_id: int,
    current_user: CurrentUser,
    service: WorkspaceServiceDep,
) -> WorkspaceResponse:
    """Get single workspace by ID."""
    return await service.get_workspace(workspace_id=workspace_id, current_user=current_user)


@router.patch(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_200_OK,
    summary="Update workspace",
    description="Update workspace name. Restricted to workspace OWNER or system administrator.",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Workspace not found"},
        422: {"description": "Validation error"},
    },
)
async def update_workspace(
    workspace_id: int,
    data: WorkspaceUpdate,
    current_user: CurrentUser,
    service: WorkspaceServiceDep,
) -> WorkspaceResponse:
    """Update workspace details."""
    return await service.update_workspace(
        workspace_id=workspace_id,
        current_user=current_user,
        data=data,
    )


@router.delete(
    "/{workspace_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete workspace",
    description="Delete a workspace and cascade to its projects and members. Restricted to OWNER or system administrator.",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Workspace not found"},
    },
)
async def delete_workspace(
    workspace_id: int,
    current_user: CurrentUser,
    service: WorkspaceServiceDep,
) -> MessageResponse:
    """Delete workspace."""
    await service.delete_workspace(workspace_id=workspace_id, current_user=current_user)
    return MessageResponse(message=SUCCESS_WORKSPACE_DELETED)


@router.get(
    "/{workspace_id}/members",
    response_model=PaginatedResponse[WorkspaceMemberResponse],
    status_code=status.HTTP_200_OK,
    summary="List workspace members",
    description="List all members belonging to the specified workspace.",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Workspace not found"},
    },
)
async def list_workspace_members(
    workspace_id: int,
    current_user: CurrentUser,
    service: WorkspaceServiceDep,
    page: int = Query(default=DEFAULT_PAGE, ge=1, description="Page number"),
    limit: int = Query(
        default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Items per page"
    ),
) -> PaginatedResponse[WorkspaceMemberResponse]:
    """List members of a workspace."""
    result = await service.list_members(
        workspace_id=workspace_id,
        current_user=current_user,
        page=page,
        limit=limit,
    )
    return PaginatedResponse[WorkspaceMemberResponse](
        items=[WorkspaceMemberResponse.model_validate(m) for m in result.items],
        total=result.total,
        page=result.page,
        limit=result.limit,
        total_pages=result.total_pages,
    )


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add member to workspace",
    description="Add an existing registered user to the workspace. Restricted to OWNER or system administrator.",
    responses={
        400: {"description": "Bad request (inactive user or invalid role)"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Workspace or user not found"},
        409: {"description": "User is already a member"},
        422: {"description": "Validation error"},
    },
)
async def add_workspace_member(
    workspace_id: int,
    data: WorkspaceMemberAdd,
    current_user: CurrentUser,
    service: WorkspaceServiceDep,
) -> WorkspaceMemberResponse:
    """Add member to workspace."""
    member = await service.add_member(
        workspace_id=workspace_id,
        current_user=current_user,
        data=data,
    )
    return WorkspaceMemberResponse.model_validate(member)


@router.patch(
    "/{workspace_id}/members/{user_id}",
    response_model=WorkspaceMemberResponse,
    status_code=status.HTTP_200_OK,
    summary="Update member role",
    description="Update a member's role (EDITOR or VIEWER). Restricted to OWNER or system administrator.",
    responses={
        400: {"description": "Bad request (cannot demote owner or assign owner role)"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Workspace or member not found"},
        422: {"description": "Validation error"},
    },
)
async def update_workspace_member_role(
    workspace_id: int,
    user_id: int,
    data: WorkspaceMemberUpdate,
    current_user: CurrentUser,
    service: WorkspaceServiceDep,
) -> WorkspaceMemberResponse:
    """Update role of a workspace member."""
    member = await service.update_member_role(
        workspace_id=workspace_id,
        target_user_id=user_id,
        current_user=current_user,
        data=data,
    )
    return WorkspaceMemberResponse.model_validate(member)


@router.delete(
    "/{workspace_id}/members/{user_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove member from workspace",
    description="Remove a member from the workspace (or allow a member to leave). Restricted to OWNER, administrator, or self.",
    responses={
        400: {"description": "Bad request (cannot remove owner)"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Workspace or member not found"},
    },
)
async def remove_workspace_member(
    workspace_id: int,
    user_id: int,
    current_user: CurrentUser,
    service: WorkspaceServiceDep,
) -> MessageResponse:
    """Remove member from workspace or self-leave."""
    await service.remove_member(
        workspace_id=workspace_id,
        target_user_id=user_id,
        current_user=current_user,
    )
    return MessageResponse(message=SUCCESS_WORKSPACE_MEMBER_REMOVED)
