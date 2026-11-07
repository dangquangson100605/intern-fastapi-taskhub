"""User SQLAlchemy model."""

import enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.workspace import Workspace


class UserRole(str, enum.Enum):
    """System-wide user roles."""

    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class User(Base):
    """Represents a registered user in the system."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole), default=UserRole.MEMBER, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    owned_workspaces: Mapped[list["Workspace"]] = relationship(
        back_populates="owner",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"
