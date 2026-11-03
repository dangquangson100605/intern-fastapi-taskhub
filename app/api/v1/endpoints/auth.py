"""Authentication API endpoints.

Handles registration, login, token refresh, and logout.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.schemas.auth import LoginRequest, RefreshTokenRequest, RegisterRequest, TokenResponse
from app.schemas.common import MessageResponse
from app.schemas.user import UserResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])


def get_auth_service(session: AsyncSession = Depends(get_db)) -> AuthService:
    """Dependency: instantiate AuthService with a DB session."""
    return AuthService(session)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Register a new user account with email, full name, and password.",
    responses={
        409: {"description": "Email already registered"},
        422: {"description": "Validation error"},
    },
)
async def register(
    data: RegisterRequest,
    service: AuthService = Depends(get_auth_service),
) -> UserResponse:
    """Register a new user."""
    user = await service.register(data)
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="User login",
    description="Authenticate with email and password to receive JWT access and refresh tokens.",
    responses={
        401: {"description": "Invalid credentials or inactive account"},
    },
)
async def login(
    data: LoginRequest,
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Login and obtain access & refresh tokens."""
    return await service.login(data)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh access token",
    description="Provide a valid refresh token to obtain a new access token.",
    responses={
        401: {"description": "Invalid, expired, or blacklisted refresh token"},
    },
)
async def refresh(
    data: RefreshTokenRequest,
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Refresh an access token using a refresh token."""
    return await service.refresh_token(data.refresh_token)


@router.post(
    "/logout",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="User logout",
    description="Revoke the refresh token by adding it to the Redis token blacklist.",
    responses={
        200: {"description": "Successfully logged out"},
    },
)
async def logout(
    data: RefreshTokenRequest,
    service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    """Logout by invalidating the refresh token."""
    await service.logout(data.refresh_token)
    return MessageResponse(message="Successfully logged out")

