"""User service — business logic for user operations."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ERROR_EMAIL_ALREADY_IN_USE, ERROR_EMAIL_ALREADY_REGISTERED
from app.core.exceptions import ConflictException, NotFoundException
from app.models.user import User
from app.repositories.base import PaginationResult
from app.repositories.user import UserRepository
from app.schemas.user import UserCreate, UserUpdate


class UserService:
    """Handles user business logic between endpoints and repository."""

    def __init__(self, session: AsyncSession, repo: UserRepository | None = None) -> None:
        self.session = session
        self.repo = repo or UserRepository(session)

    async def create_user(self, data: UserCreate) -> User:
        """Register a new user (Day 1: simple version without hashing)."""
        existing = await self.repo.get_by_email(data.email)
        if existing:
            raise ConflictException(ERROR_EMAIL_ALREADY_REGISTERED.format(email=data.email))

        return await self.repo.create(
            email=data.email,
            full_name=data.full_name,
            hashed_password=data.password,
        )

    async def get_user_by_id(self, user_id: int) -> User:
        """Get user by ID or raise 404."""
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise NotFoundException("User", user_id)
        return user

    async def get_user_by_email(self, email: str) -> User | None:
        """Find user by email (used by auth service)."""
        return await self.repo.get_by_email(email)

    async def list_users(
        self,
        page: int = 1,
        limit: int = 20,
    ) -> PaginationResult[User]:
        """List all users with pagination."""
        return await self.repo.get_all(page=page, limit=limit)

    async def update_user(self, user_id: int, data: UserUpdate) -> User:
        """Update user profile fields."""
        if data.email:
            existing = await self.repo.get_by_email(data.email)
            if existing and existing.id != user_id:
                raise ConflictException(ERROR_EMAIL_ALREADY_IN_USE.format(email=data.email))

        update_data = data.model_dump(exclude_unset=True)
        user = await self.repo.update(user_id, **update_data)
        if not user:
            raise NotFoundException("User", user_id)
        return user

    async def delete_user(self, user_id: int) -> bool:
        """Delete a user by ID."""
        deleted = await self.repo.delete(user_id)
        if not deleted:
            raise NotFoundException("User", user_id)
        return True
