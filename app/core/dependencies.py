"""Shared FastAPI dependencies.

Provides reusable dependency functions for database sessions,
current user resolution, and security schemes.
"""

from collections.abc import AsyncGenerator

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.exceptions import UnauthorizedException
from app.core.security import decode_token
from app.models.user import User
from app.repositories.user import UserRepository

# HTTPBearer scheme: enables Swagger UI "Authorize" button with Bearer token
http_bearer = HTTPBearer(
    scheme_name="BearerAuth",
    description="Enter JWT access token with or without Bearer prefix",
    auto_error=True,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session, ensuring it is closed after use."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(http_bearer),
    session: AsyncSession = Depends(get_db),
) -> User:
    """Validate Bearer access token and return the current authenticated User."""
    token = credentials.credentials
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise UnauthorizedException("Invalid token type: expected access token")

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise UnauthorizedException("Could not validate credentials")

    try:
        user_id = int(user_id_str)
    except ValueError as e:
        raise UnauthorizedException("Malformed user identity in token") from e

    repo = UserRepository(session)
    user = await repo.get_by_id(user_id)
    if not user:
        raise UnauthorizedException("User not found")
    if not user.is_active:
        raise UnauthorizedException("User account is inactive")

    return user
