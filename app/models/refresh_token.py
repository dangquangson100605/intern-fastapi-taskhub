"""RefreshToken SQLAlchemy model for persistent token rotation and revocation."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import TOKEN_JTI_MAX_LENGTH
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class RefreshToken(Base):
    """Persisted refresh token record supporting atomic rotation and reuse detection."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    jti: Mapped[str] = mapped_column(
        String(TOKEN_JTI_MAX_LENGTH),
        unique=True,
        index=True,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean,
        server_default="0",
        default=False,
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )
    replaced_by_jti: Mapped[str | None] = mapped_column(
        String(TOKEN_JTI_MAX_LENGTH),
        nullable=True,
    )

    user: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        return f"<RefreshToken id={self.id} user_id={self.user_id} revoked={self.revoked}>"

