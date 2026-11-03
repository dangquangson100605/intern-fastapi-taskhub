"""Auth service — business logic for user authentication."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, UnauthorizedException
from app.core.redis import add_token_to_blacklist, is_token_blacklisted
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse


class AuthService:
    """Handles authentication business logic."""

    def __init__(self, session: AsyncSession) -> None:
        self.user_repo = UserRepository(session)
        self.session = session

    async def register(self, data: RegisterRequest) -> User:
        """Register a new user account with hashed password."""
        existing = await self.user_repo.get_by_email(data.email)
        if existing:
            raise ConflictException(f"Email '{data.email}' is already registered")

        hashed_pwd = hash_password(data.password)
        return await self.user_repo.create(
            email=data.email,
            full_name=data.full_name,
            hashed_password=hashed_pwd,
        )

    async def login(self, data: LoginRequest) -> TokenResponse:
        """Authenticate user and return a JWT access and refresh token pair."""
        user = await self.user_repo.get_by_email(data.email)
        if not user or not verify_password(data.password, user.hashed_password):
            raise UnauthorizedException("Invalid email or password")

        if not user.is_active:
            raise UnauthorizedException("User account is inactive")

        access_token = create_access_token(
            subject=user.id,
            extra_claims={"email": user.email, "role": user.role.value},
        )
        refresh_token = create_refresh_token(subject=user.id)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """Issue a new access token using a valid refresh token."""
        if await is_token_blacklisted(refresh_token):
            raise UnauthorizedException("Refresh token has been revoked")

        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise UnauthorizedException("Invalid token type: expected refresh token")

        user_id_str = payload.get("sub")
        if not user_id_str:
            raise UnauthorizedException("Invalid token payload")

        try:
            user_id = int(user_id_str)
        except ValueError as e:
            raise UnauthorizedException("Invalid user id in token") from e

        user = await self.user_repo.get_by_id(user_id)
        if not user or not user.is_active:
            raise UnauthorizedException("User not found or inactive")

        new_access_token = create_access_token(
            subject=user.id,
            extra_claims={"email": user.email, "role": user.role.value},
        )

        return TokenResponse(
            access_token=new_access_token,
            refresh_token=refresh_token,
        )

    async def logout(self, refresh_token: str) -> None:
        """Revoke a refresh token by adding it to Redis blacklist."""
        try:
            payload = decode_token(refresh_token)
            exp = payload.get("exp")
            if exp:
                now_ts = datetime.now(UTC).timestamp()
                remaining_seconds = max(int(exp - now_ts), 60)
            else:
                remaining_seconds = 604800  # Default 7 days
        except UnauthorizedException:
            # Token already expired or invalid, still blacklist it with short TTL
            remaining_seconds = 3600

        await add_token_to_blacklist(refresh_token, expire_seconds=remaining_seconds)
