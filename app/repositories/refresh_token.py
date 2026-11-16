"""RefreshToken repository — atomic rotation, lookup, and session revocation."""

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken
from app.repositories.base import BaseRepository


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    """Repository for persistent refresh token storage and atomic revocation."""

    model = RefreshToken

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def create_token(
        self,
        user_id: int,
        jti: str,
        expires_at: datetime,
    ) -> RefreshToken:
        """Persist a newly issued refresh token record."""
        return await self.create(
            user_id=user_id,
            jti=jti,
            expires_at=expires_at.replace(tzinfo=None),
        )

    async def get_by_jti(self, jti: str, for_update: bool = False) -> RefreshToken | None:
        """Look up a refresh token by JTI, optionally acquiring a row lock."""
        query = select(RefreshToken).where(RefreshToken.jti == jti)
        if for_update:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def atomic_revoke_by_jti(
        self,
        jti: str,
        replaced_by_jti: str | None = None,
    ) -> bool:
        """Atomically revoke an active token; returns False if already revoked or absent."""
        now_utc = datetime.now(UTC).replace(tzinfo=None)
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.jti == jti, RefreshToken.revoked.is_(False))
            .values(
                revoked=True,
                revoked_at=now_utc,
                replaced_by_jti=replaced_by_jti,
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        return int(result.rowcount or 0) == 1

    async def revoke_all_for_user(self, user_id: int) -> int:
        """Revoke all active refresh tokens belonging to a user."""
        now_utc = datetime.now(UTC).replace(tzinfo=None)
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False))
            .values(
                revoked=True,
                revoked_at=now_utc,
            )
        )
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        return int(result.rowcount or 0)

