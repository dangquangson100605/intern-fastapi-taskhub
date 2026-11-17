"""Project API endpoints for creation, listing, updating, and archiving."""

from fastapi import APIRouter, status

from app.core.dependencies import CurrentUser, PaginationDep, ProjectServiceDep
from app.core.messages import SUCCESS_PROJECT_DELETED
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate

router = APIRouter(tags=["Projects"])


@router.post(
    "/workspaces/{workspace_id}/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
    description="Create a project inside the specified workspace. Requires EDITOR or OWNER role.",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Workspace not found"},
        422: {"description": "Validation error"},
    },
)
async def create_project(
    workspace_id: int,
    data: ProjectCreate,
    current_user: CurrentUser,
    service: ProjectServiceDep,
) -> ProjectResponse:
    """Create project in workspace."""
    return await service.create_project(
        workspace_id=workspace_id,
        current_user=current_user,
        data=data,
    )


@router.get(
    "/workspaces/{workspace_id}/projects",
    response_model=PaginatedResponse[ProjectResponse],
    status_code=status.HTTP_200_OK,
    summary="List workspace projects",
    description="Retrieve paginated projects within a workspace for any member.",
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "Workspace not found"},
    },
)
async def list_workspace_projects(
    workspace_id: int,
    pagination: PaginationDep,
    current_user: CurrentUser,
    service: ProjectServiceDep,
) -> PaginatedResponse[ProjectResponse]:
    """List projects of a workspace."""
    return await service.list_projects(
        workspace_id=workspace_id,
        current_user=current_user,
        pagination=pagination,
    )


@router.get(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Get project details",
    description="Fetch single project details ensuring caller has membership in parent workspace.",
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "Project not found"},
    },
)
async def get_project(
    project_id: int,
    current_user: CurrentUser,
    service: ProjectServiceDep,
) -> ProjectResponse:
    """Get project by ID."""
    return await service.get_project(project_id=project_id, current_user=current_user)


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Update project",
    description="Modify project name or description. Blocked if project is archived.",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Project not found"},
        409: {"description": "Project is archived"},
        422: {"description": "Validation error"},
    },
)
async def update_project(
    project_id: int,
    data: ProjectUpdate,
    current_user: CurrentUser,
    service: ProjectServiceDep,
) -> ProjectResponse:
    """Update project details."""
    return await service.update_project(
        project_id=project_id,
        current_user=current_user,
        data=data,
    )


@router.patch(
    "/projects/{project_id}/archive",
    response_model=ProjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Archive project",
    description="Set project lifecycle status to ARCHIVED. Requires write role.",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Project not found"},
        409: {"description": "Project is already archived"},
    },
)
async def archive_project(
    project_id: int,
    current_user: CurrentUser,
    service: ProjectServiceDep,
) -> ProjectResponse:
    """Archive project."""
    return await service.archive_project(project_id=project_id, current_user=current_user)


@router.patch(
    "/projects/{project_id}/unarchive",
    response_model=ProjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Unarchive project",
    description="Restore project lifecycle status to ACTIVE. Requires write role.",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Project not found"},
        409: {"description": "Project is already active"},
    },
)
async def unarchive_project(
    project_id: int,
    current_user: CurrentUser,
    service: ProjectServiceDep,
) -> ProjectResponse:
    """Unarchive project."""
    return await service.unarchive_project(project_id=project_id, current_user=current_user)


@router.delete(
    "/projects/{project_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete project",
    description="Delete project and cascade delete associated tasks.",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Project not found"},
    },
)
async def delete_project(
    project_id: int,
    current_user: CurrentUser,
    service: ProjectServiceDep,
) -> MessageResponse:
    """Delete project."""
    await service.delete_project(project_id=project_id, current_user=current_user)
    return MessageResponse(message=SUCCESS_PROJECT_DELETED)
