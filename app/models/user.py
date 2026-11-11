"""User SQLAlchemy model."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import (
    USER_EMAIL_MAX_LENGTH,
    USER_FULL_NAME_MAX_LENGTH,
    USER_PASSWORD_HASH_MAX_LENGTH,
)
from app.core.database import Base
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.workspace import Workspace


class User(Base):
    """Represents a registered user in the system."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(USER_EMAIL_MAX_LENGTH),
        unique=True,
        index=True,
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        String(USER_FULL_NAME_MAX_LENGTH),
        nullable=False,
    )
    hashed_password: Mapped[str] = mapped_column(
        String(USER_PASSWORD_HASH_MAX_LENGTH),
        nullable=False,
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, create_constraint=True),
        server_default=UserRole.MEMBER.value,
        default=UserRole.MEMBER,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        server_default="1",
        default=True,
        nullable=False,
    )

    owned_workspaces: Mapped[list["Workspace"]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"
