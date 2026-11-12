"""User service — business logic for user management and authorization guards."""

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.core.messages import (
    ERROR_CANNOT_DELETE_SELF,
    ERROR_CANNOT_DELETE_USER_WITH_DEPENDENCIES,
    ERROR_CANNOT_REMOVE_LAST_ADMIN,
    ERROR_EMAIL_ALREADY_IN_USE,
    ERROR_EMAIL_ALREADY_REGISTERED,
)
from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.base import PaginationResult
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.schemas.user import AdminUserCreate, AdminUserUpdate, UserCreate, UserUpdate


def is_duplicate_entry_error(exc: IntegrityError) -> bool:
    """Return True if an IntegrityError was caused by a unique constraint violation."""
    orig_msg = str(getattr(exc, "orig", exc)).lower()
    return "duplicate" in orig_msg or "unique" in orig_msg or "1062" in orig_msg


class UserService:
    """Handles user business logic between endpoints and repositories."""

    def __init__(
        self,
        session: AsyncSession,
        repo: UserRepository | None = None,
        refresh_repo: RefreshTokenRepository | None = None,
    ) -> None:
        self.session = session
        self.repo = repo or UserRepository(session)
        self.refresh_repo = refresh_repo or RefreshTokenRepository(session)

    async def create_user(
        self,
        data: UserCreate | AdminUserCreate,
        role: UserRole | None = None,
    ) -> User:
        """Register a new user directly and map unique email conflicts to 409."""
        assigned_role = role if role is not None else UserRole.MEMBER
        if isinstance(data, AdminUserCreate) and role is None:
            assigned_role = data.role

        normalized_email = data.email.lower()
        hashed = await run_in_threadpool(hash_password, data.password)

        try:
            return await self.repo.create(
                email=normalized_email,
                full_name=data.full_name,
                hashed_password=hashed,
                role=assigned_role,
            )
        except IntegrityError as exc:
            await self.session.rollback()
            if is_duplicate_entry_error(exc):
                raise ConflictException(
                    ERROR_EMAIL_ALREADY_REGISTERED.format(email=normalized_email)
                ) from exc
            raise

    async def get_user_by_id(self, user_id: int) -> User:
        """Get user by ID or raise 404."""
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise NotFoundException("User", user_id)
        return user

    async def get_user_by_email(self, email: str) -> User | None:
        """Find user by normalized email address."""
        return await self.repo.get_by_email(email.lower())

    async def list_users(
        self,
        page: int = 1,
        limit: int = 20,
    ) -> PaginationResult[User]:
        """List all users with pagination."""
        return await self.repo.get_all(page=page, limit=limit)

    async def _apply_update(self, user_id: int, update_data: dict[str, Any]) -> User:
        """Apply partial user updates and translate email uniqueness errors to 409."""
        if "email" in update_data and isinstance(update_data["email"], str):
            update_data["email"] = update_data["email"].lower()

        try:
            user = await self.repo.update(user_id, **update_data)
        except IntegrityError as exc:
            await self.session.rollback()
            if is_duplicate_entry_error(exc):
                conflict_email = str(update_data.get("email", ""))
                raise ConflictException(
                    ERROR_EMAIL_ALREADY_IN_USE.format(email=conflict_email)
                ) from exc
            raise

        if not user:
            raise NotFoundException("User", user_id)
        return user

    async def update_profile(self, user: User, data: UserUpdate) -> User:
        """Update the authenticated user's own profile fields."""
        update_data = data.model_dump(exclude_unset=True)
        return await self._apply_update(user.id, update_data)

    async def admin_update_user(self, user_id: int, data: AdminUserUpdate) -> User:
        """Allow an admin to update a user while keeping at least one active admin."""
        target = await self.get_user_by_id(user_id)

        new_role = data.role if data.role is not None else target.role
        new_active = data.is_active if data.is_active is not None else target.is_active
        if (
            target.role == UserRole.ADMIN
            and target.is_active
            and (new_role != UserRole.ADMIN or not new_active)
            and await self.repo.count_active_admins() <= 1
        ):
            raise BadRequestException(ERROR_CANNOT_REMOVE_LAST_ADMIN)

        was_active = target.is_active
        update_data = data.model_dump(exclude_unset=True)
        updated = await self._apply_update(user_id, update_data)

        if was_active and not updated.is_active:
            await self.refresh_repo.revoke_all_for_user(user_id)

        return updated

    async def delete_user(self, target_user_id: int, current_user: User) -> bool:
        """Delete a target user while blocking self-deletion and deleting the last active admin."""
        if target_user_id == current_user.id:
            raise BadRequestException(ERROR_CANNOT_DELETE_SELF)

        target = await self.get_user_by_id(target_user_id)
        if (
            target.role == UserRole.ADMIN
            and target.is_active
            and await self.repo.count_active_admins() <= 1
        ):
            raise BadRequestException(ERROR_CANNOT_REMOVE_LAST_ADMIN)

        try:
            deleted = await self.repo.delete(target_user_id)
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictException(ERROR_CANNOT_DELETE_USER_WITH_DEPENDENCIES) from exc

        if not deleted:
            raise NotFoundException("User", target_user_id)
        return True
