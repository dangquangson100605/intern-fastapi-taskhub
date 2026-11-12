"""Shared FastAPI dependencies using Annotated pattern."""

from collections.abc import AsyncGenerator, Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import BEARER_TOKEN_TYPE
from app.core.database import AsyncSessionLocal
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.messages import (
    ERROR_INACTIVE_USER,
    ERROR_INVALID_TOKEN,
    ERROR_NOT_AUTHENTICATED,
    ERROR_PERMISSION_DENIED,
    ERROR_TOKEN_REVOKED,
)
from app.core.redis import TokenBlacklistService, redis_client
from app.core.security import TokenPayload, decode_token
from app.models.enums import TokenType, UserRole
from app.models.user import User
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.services.auth import AuthService
from app.services.user import UserService

bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Enter JWT access token",
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session and handle transaction commit/rollback."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_db)]
DbSession = SessionDep


def get_token_blacklist() -> TokenBlacklistService:
    """Dependency: instantiate Redis-backed TokenBlacklistService."""
    return TokenBlacklistService(redis_client)


BlacklistDep = Annotated[TokenBlacklistService, Depends(get_token_blacklist)]


def get_user_repository(session: SessionDep) -> UserRepository:
    """Dependency: instantiate UserRepository with a DB session."""
    return UserRepository(session)


UserRepoDep = Annotated[UserRepository, Depends(get_user_repository)]


def get_refresh_token_repository(session: SessionDep) -> RefreshTokenRepository:
    """Dependency: instantiate RefreshTokenRepository with a DB session."""
    return RefreshTokenRepository(session)


RefreshTokenRepoDep = Annotated[RefreshTokenRepository, Depends(get_refresh_token_repository)]


def get_user_service(
    session: SessionDep,
    repo: UserRepoDep,
    refresh_repo: RefreshTokenRepoDep,
) -> UserService:
    """Dependency: instantiate UserService with injected repositories."""
    return UserService(session, repo=repo, refresh_repo=refresh_repo)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


def get_auth_service(
    session: SessionDep,
    user_repo: UserRepoDep,
    refresh_repo: RefreshTokenRepoDep,
    blacklist: BlacklistDep,
    user_service: UserServiceDep,
) -> AuthService:
    """Dependency: instantiate AuthService with repositories and Redis blacklist."""
    return AuthService(
        session=session,
        user_repo=user_repo,
        refresh_repo=refresh_repo,
        blacklist=blacklist,
        user_service=user_service,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_token_payload(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    blacklist: BlacklistDep,
) -> TokenPayload:
    """Extract, decode, type-check, and blacklist-check the bearer access token."""
    if (
        credentials is None
        or credentials.scheme.lower() != BEARER_TOKEN_TYPE
        or not credentials.credentials
    ):
        raise UnauthorizedException(ERROR_NOT_AUTHENTICATED)

    payload = decode_token(credentials.credentials, expected_type=TokenType.ACCESS)
    if await blacklist.is_blacklisted(payload.jti):
        raise UnauthorizedException(ERROR_TOKEN_REVOKED)
    return payload


CurrentTokenPayload = Annotated[TokenPayload, Depends(get_current_token_payload)]


async def get_current_user(
    payload: CurrentTokenPayload,
    user_repo: UserRepoDep,
) -> User:
    """Resolve authenticated active user from the validated access token payload."""
    user = await user_repo.get_by_id(payload.user_id)
    if user is None:
        raise UnauthorizedException(ERROR_INVALID_TOKEN)
    if not user.is_active:
        raise UnauthorizedException(ERROR_INACTIVE_USER)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*allowed_roles: UserRole) -> Callable[[CurrentUser], User]:
    """Build a dependency verifying that the current user holds an allowed role."""

    def role_checker(current_user: CurrentUser) -> User:
        if current_user.role not in allowed_roles:
            raise ForbiddenException(ERROR_PERMISSION_DENIED)
        return current_user

    return role_checker


AdminUser = Annotated[User, Depends(require_role(UserRole.ADMIN))]
