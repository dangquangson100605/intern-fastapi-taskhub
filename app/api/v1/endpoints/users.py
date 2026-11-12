"""User API endpoints for self-service profile management and admin user control."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.constants import DEFAULT_LIMIT, DEFAULT_PAGE, MAX_LIMIT
from app.core.dependencies import (
    AdminUser,
    AuthServiceDep,
    CurrentUser,
    UserServiceDep,
)
from app.core.exceptions import ForbiddenException
from app.core.messages import (
    ERROR_PERMISSION_DENIED,
    SUCCESS_PASSWORD_CHANGED,
    SUCCESS_USER_DELETED,
)
from app.models.enums import UserRole
from app.schemas.auth import ChangePasswordRequest
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.user import AdminUserCreate, AdminUserUpdate, UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
    description="Return the profile of the currently authenticated user.",
    responses={
        401: {"description": "Not authenticated or invalid token"},
    },
)
async def get_my_profile(current_user: CurrentUser) -> UserResponse:
    """Return the authenticated user's profile."""
    return UserResponse.model_validate(current_user)


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update current user profile",
    description="Update the authenticated user's own full_name or email.",
    responses={
        401: {"description": "Not authenticated"},
        409: {"description": "Email already in use"},
        422: {"description": "Validation error"},
    },
)
async def update_my_profile(
    data: UserUpdate,
    current_user: CurrentUser,
    service: UserServiceDep,
) -> UserResponse:
    """Update the authenticated user's profile fields."""
    user = await service.update_profile(current_user, data)
    return UserResponse.model_validate(user)


@router.patch(
    "/me/password",
    response_model=MessageResponse,
    summary="Change current user password",
    description="Verify current password, set a new password, and revoke existing refresh tokens.",
    responses={
        400: {"description": "Incorrect current password or same password"},
        401: {"description": "Not authenticated"},
        422: {"description": "Validation error"},
    },
)
async def change_my_password(
    data: ChangePasswordRequest,
    current_user: CurrentUser,
    auth_service: AuthServiceDep,
) -> MessageResponse:
    """Rotate password for the authenticated user and invalidate refresh sessions."""
    await auth_service.change_password(current_user, data)
    return MessageResponse(message=SUCCESS_PASSWORD_CHANGED)


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user (Admin)",
    description="Admin-only endpoint to create a user with an explicit role.",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        409: {"description": "Email already registered"},
        422: {"description": "Validation error"},
    },
)
async def create_user(
    data: AdminUserCreate,
    admin: AdminUser,
    service: UserServiceDep,
) -> UserResponse:
    """Create a user account as an administrator."""
    user = await service.create_user(data)
    return UserResponse.model_validate(user)


@router.get(
    "",
    response_model=PaginatedResponse[UserResponse],
    summary="List all users (Admin)",
    description="Admin-only paginated listing of all users.",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
    },
)
async def list_users(
    admin: AdminUser,
    service: UserServiceDep,
    page: Annotated[int, Query(ge=1, description="Page number")] = DEFAULT_PAGE,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Items per page")] = DEFAULT_LIMIT,
) -> PaginatedResponse[UserResponse]:
    """List all users with pagination."""
    result = await service.list_users(page=page, limit=limit)
    return PaginatedResponse(
        items=[UserResponse.model_validate(u) for u in result.items],
        total=result.total,
        page=result.page,
        limit=result.limit,
        total_pages=result.total_pages,
    )


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get user by ID",
    description="Retrieve a user profile. Members may only access their own user ID; admins may access any.",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "User not found"},
    },
)
async def get_user(
    user_id: int,
    current_user: CurrentUser,
    service: UserServiceDep,
) -> UserResponse:
    """Retrieve a user by ID with self/admin authorization."""
    if current_user.id != user_id and current_user.role != UserRole.ADMIN:
        raise ForbiddenException(ERROR_PERMISSION_DENIED)
    user = await service.get_user_by_id(user_id)
    return UserResponse.model_validate(user)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    summary="Update a user (Admin)",
    description="Admin-only update for a user's profile, role, or active status.",
    responses={
        400: {"description": "Cannot demote or deactivate the last active admin"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "User not found"},
        409: {"description": "Email already in use"},
        422: {"description": "Validation error"},
    },
)
async def update_user(
    user_id: int,
    data: AdminUserUpdate,
    admin: AdminUser,
    service: UserServiceDep,
) -> UserResponse:
    """Update a user's fields as an administrator."""
    user = await service.admin_update_user(user_id, data)
    return UserResponse.model_validate(user)


@router.delete(
    "/{user_id}",
    response_model=MessageResponse,
    summary="Delete a user (Admin)",
    description="Admin-only deletion. Blocks self-deletion and deleting the last active admin.",
    responses={
        400: {"description": "Cannot delete self or the last active admin"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "User not found"},
        409: {"description": "User has dependent records"},
    },
)
async def delete_user(
    user_id: int,
    admin: AdminUser,
    service: UserServiceDep,
) -> MessageResponse:
    """Delete a target user as an administrator."""
    await service.delete_user(user_id, current_user=admin)
    return MessageResponse(message=SUCCESS_USER_DELETED)
