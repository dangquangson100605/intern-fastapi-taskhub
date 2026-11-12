"""Authentication service — registration, login, token rotation, logout, and password changes."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.constants import BEARER_TOKEN_TYPE
from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    UnauthorizedException,
)
from app.core.messages import (
    ERROR_INACTIVE_USER,
    ERROR_INCORRECT_CURRENT_PASSWORD,
    ERROR_INVALID_CREDENTIALS,
    ERROR_INVALID_TOKEN,
    ERROR_NEW_PASSWORD_SAME_AS_OLD,
    ERROR_PERMISSION_DENIED,
    ERROR_REFRESH_TOKEN_REUSED,
)
from app.core.redis import TokenBlacklistService
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    TokenPayload,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.enums import TokenType, UserRole
from app.models.user import User
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
)
from app.services.user import UserService

settings = get_settings()


class AuthService:
    """Handles user authentication, JWT issuance, atomic refresh rotation, and logout."""

    def __init__(
        self,
        session: AsyncSession,
        user_repo: UserRepository,
        refresh_repo: RefreshTokenRepository,
        blacklist: TokenBlacklistService,
        user_service: UserService | None = None,
    ) -> None:
        self.session = session
        self.user_repo = user_repo
        self.refresh_repo = refresh_repo
        self.blacklist = blacklist
        self.user_service = user_service or UserService(
            session, repo=user_repo, refresh_repo=refresh_repo
        )

    async def register(self, data: RegisterRequest) -> User:
        """Self-register a new member account without allowing client role selection."""
        return await self.user_service.create_user(data, role=UserRole.MEMBER)

    async def _issue_token_pair(self, user: User) -> TokenResponse:
        """Create and persist a fresh access + refresh token pair for the given user."""
        access_token = create_access_token(user.id, user.role)
        refresh_token, jti, expires_at = create_refresh_token(user.id)
        await self.refresh_repo.create_token(
            user_id=user.id,
            jti=jti,
            expires_at=expires_at,
        )
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=BEARER_TOKEN_TYPE,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def login(self, data: LoginRequest) -> TokenResponse:
        """Authenticate credentials with constant-time hash verification against unknown emails."""
        user = await self.user_repo.get_by_email(data.email.lower())
        target_hash = user.hashed_password if user is not None else DUMMY_PASSWORD_HASH
        is_valid = await run_in_threadpool(verify_password, data.password, target_hash)
        if user is None or not is_valid:
            raise UnauthorizedException(ERROR_INVALID_CREDENTIALS)

        if not user.is_active:
            raise UnauthorizedException(ERROR_INACTIVE_USER)

        return await self._issue_token_pair(user)

    async def refresh(self, refresh_token: str) -> TokenResponse:
        """Atomically rotate a refresh token in one transaction with reuse detection."""
        payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)

        if await self.blacklist.is_blacklisted(payload.jti):
            await self.refresh_repo.revoke_all_for_user(payload.user_id)
            await self.session.commit()
            raise UnauthorizedException(ERROR_REFRESH_TOKEN_REUSED)

        token_record = await self.refresh_repo.get_by_jti(payload.jti, for_update=True)
        if token_record is None:
            raise UnauthorizedException(ERROR_INVALID_TOKEN)

        if token_record.revoked:
            await self.refresh_repo.revoke_all_for_user(token_record.user_id)
            await self.session.commit()
            raise UnauthorizedException(ERROR_REFRESH_TOKEN_REUSED)

        now_utc = datetime.now(UTC).replace(tzinfo=None)
        if token_record.expires_at <= now_utc:
            raise UnauthorizedException(ERROR_INVALID_TOKEN)

        user = await self.user_repo.get_by_id(payload.user_id)
        if user is None:
            raise UnauthorizedException(ERROR_INVALID_TOKEN)

        if not user.is_active:
            raise UnauthorizedException(ERROR_INACTIVE_USER)

        access_token = create_access_token(user.id, user.role)
        new_refresh_token, new_jti, new_expires_at = create_refresh_token(user.id)

        revoked_ok = await self.refresh_repo.atomic_revoke_by_jti(
            payload.jti,
            replaced_by_jti=new_jti,
        )
        if not revoked_ok:
            await self.refresh_repo.revoke_all_for_user(user.id)
            await self.session.commit()
            raise UnauthorizedException(ERROR_REFRESH_TOKEN_REUSED)

        await self.refresh_repo.create_token(
            user_id=user.id,
            jti=new_jti,
            expires_at=new_expires_at,
        )
        return TokenResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            token_type=BEARER_TOKEN_TYPE,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def logout(
        self,
        access_payload: TokenPayload,
        refresh_token: str | None = None,
    ) -> None:
        """Validate optional refresh token first, revoke it in DB, then blacklist tokens in Redis."""
        refresh_payload: TokenPayload | None = None
        if refresh_token is not None:
            refresh_payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)
            if refresh_payload.user_id != access_payload.user_id:
                raise ForbiddenException(ERROR_PERMISSION_DENIED)

            revoked = await self.refresh_repo.atomic_revoke_by_jti(refresh_payload.jti)
            if not revoked:
                existing = await self.refresh_repo.get_by_jti(refresh_payload.jti)
                if existing is not None and existing.revoked:
                    await self.refresh_repo.revoke_all_for_user(access_payload.user_id)
                    await self.session.commit()
                    raise UnauthorizedException(ERROR_REFRESH_TOKEN_REUSED)
                raise UnauthorizedException(ERROR_INVALID_TOKEN)

            await self.blacklist.blacklist_token(refresh_payload.jti, refresh_payload.exp)

        await self.blacklist.blacklist_token(access_payload.jti, access_payload.exp)

    async def change_password(
        self,
        user: User,
        access_payload: TokenPayload,
        data: ChangePasswordRequest,
    ) -> None:
        """Verify password, update hash and timestamp, and invalidate all active tokens."""
        is_valid = await run_in_threadpool(
            verify_password, data.current_password, user.hashed_password
        )
        if not is_valid:
            raise BadRequestException(ERROR_INCORRECT_CURRENT_PASSWORD)

        if data.new_password == data.current_password:
            raise BadRequestException(ERROR_NEW_PASSWORD_SAME_AS_OLD)

        new_hashed = await run_in_threadpool(hash_password, data.new_password)
        changed_at = datetime.now(UTC).replace(tzinfo=None)
        await self.user_repo.update(
            user.id,
            hashed_password=new_hashed,
            password_changed_at=changed_at,
        )
        await self.refresh_repo.revoke_all_for_user(user.id)
        await self.blacklist.blacklist_token(access_payload.jti, access_payload.exp)
