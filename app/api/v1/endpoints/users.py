"""User API endpoints.

Provides CRUD operations for the User resource.
"""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.constants import (
    DEFAULT_LIMIT,
    DEFAULT_PAGE,
    MAX_LIMIT,
    SUCCESS_USER_DELETED,
)
from app.core.dependencies import UserServiceDep
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.user import UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["Users"])


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user",
    description="Register a new user with email, full name, and password.",
    responses={
        409: {"description": "Email already registered"},
    },
)
async def create_user(
    data: UserCreate,
    service: UserServiceDep,
) -> UserResponse:
    """Create a new user account."""
    user = await service.create_user(data)
    return UserResponse.model_validate(user)


@router.get(
    "",
    response_model=PaginatedResponse[UserResponse],
    summary="List all users",
    description="Retrieve a paginated list of all users.",
)
async def list_users(
    service: UserServiceDep,
    page: Annotated[int, Query(ge=1, description="Page number")] = DEFAULT_PAGE,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Items per page")] = DEFAULT_LIMIT,
) -> PaginatedResponse[UserResponse]:
    """List users with pagination."""
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
    responses={
        404: {"description": "User not found"},
    },
)
async def get_user(
    user_id: int,
    service: UserServiceDep,
) -> UserResponse:
    """Retrieve a single user by their ID."""
    user = await service.get_user_by_id(user_id)
    return UserResponse.model_validate(user)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    summary="Update user profile",
    description="Partially update a user's profile (full_name, email).",
    responses={
        404: {"description": "User not found"},
        409: {"description": "Email already in use"},
    },
)
async def update_user(
    user_id: int,
    data: UserUpdate,
    service: UserServiceDep,
) -> UserResponse:
    """Update user profile fields."""
    user = await service.update_user(user_id, data)
    return UserResponse.model_validate(user)


@router.delete(
    "/{user_id}",
    response_model=MessageResponse,
    summary="Delete a user",
    responses={
        404: {"description": "User not found"},
    },
)
async def delete_user(
    user_id: int,
    service: UserServiceDep,
) -> MessageResponse:
    """Delete a user by their ID."""
    await service.delete_user(user_id)
    return MessageResponse(message=SUCCESS_USER_DELETED)
