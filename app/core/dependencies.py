"""Shared FastAPI dependencies.

Provides reusable dependency functions for database sessions,
repositories, and services using Annotated pattern.
"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.repositories.user import UserRepository
from app.services.user import UserService


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session, ensuring it is closed after use."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_db)]


def get_user_repository(session: SessionDep) -> UserRepository:
    """Dependency: instantiate UserRepository with a DB session."""
    return UserRepository(session)


UserRepoDep = Annotated[UserRepository, Depends(get_user_repository)]


def get_user_service(
    session: SessionDep,
    repo: UserRepoDep,
) -> UserService:
    """Dependency: instantiate UserService with an injected UserRepository."""
    return UserService(session, repo=repo)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]
