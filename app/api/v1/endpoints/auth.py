"""Authentication API endpoints for registration, login, refresh, and logout."""

from typing import Annotated

from fastapi import APIRouter, Body, status

from app.core.dependencies import (
    AuthServiceDep,
    CurrentTokenPayload,
)
from app.core.messages import SUCCESS_LOGOUT
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.common import MessageResponse
from app.schemas.user import UserResponse

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
    description="Public self-registration endpoint. Newly registered users always receive the MEMBER role.",
    responses={
        409: {"description": "Email already registered"},
        422: {"description": "Validation error"},
    },
)
async def register(
    data: RegisterRequest,
    service: AuthServiceDep,
) -> UserResponse:
    """Register a new member account."""
    user = await service.register(data)
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and obtain JWT tokens",
    description="Verify email and password, returning an access token and refresh token.",
    responses={
        401: {"description": "Invalid credentials or inactive user"},
        422: {"description": "Validation error"},
    },
)
async def login(
    data: LoginRequest,
    service: AuthServiceDep,
) -> TokenResponse:
    """Authenticate user credentials and issue token pair."""
    return await service.login(data)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate refresh token",
    description="Exchange a valid refresh token for a new access and refresh token pair.",
    responses={
        401: {"description": "Invalid, expired, or revoked refresh token"},
        422: {"description": "Validation error"},
    },
)
async def refresh_token(
    data: RefreshTokenRequest,
    service: AuthServiceDep,
) -> TokenResponse:
    """Atomically rotate a refresh token and issue new tokens."""
    return await service.refresh(data.refresh_token)


@router.post(
    "/logout",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Logout and revoke tokens",
    description="Blacklist the current access token in Redis and optionally revoke the provided refresh token.",
    responses={
        401: {"description": "Not authenticated or invalid token"},
        403: {"description": "Refresh token belongs to another user"},
    },
)
async def logout(
    token_payload: CurrentTokenPayload,
    service: AuthServiceDep,
    data: Annotated[LogoutRequest | None, Body()] = None,
) -> MessageResponse:
    """Invalidate the caller's active session tokens."""
    refresh = data.refresh_token if data is not None else None
    await service.logout(access_payload=token_payload, refresh_token=refresh)
    return MessageResponse(message=SUCCESS_LOGOUT)
