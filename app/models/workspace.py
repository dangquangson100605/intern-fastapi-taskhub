"""Workspace and WorkspaceMember SQLAlchemy models."""

import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.user import User


class WorkspaceRole(str, enum.Enum):
    """Roles within a specific workspace."""

    OWNER = "OWNER"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"


class Workspace(Base):
    """A workspace groups projects and members together."""

    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    owner: Mapped["User"] = relationship(
        back_populates="owned_workspaces",
        lazy="selectin",
    )
    members: Mapped[list["WorkspaceMember"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    projects: Mapped[list["Project"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Workspace id={self.id} name={self.name!r}>"


class WorkspaceMember(Base):
    """Junction table: user membership + role in a workspace."""

    __tablename__ = "workspace_members"

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[WorkspaceRole] = mapped_column(
        Enum(WorkspaceRole), default=WorkspaceRole.VIEWER, nullable=False
    )

    workspace: Mapped["Workspace"] = relationship(
        back_populates="members",
        lazy="selectin",
    )
    user: Mapped["User"] = relationship(lazy="selectin")

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_user"),
    )

    def __repr__(self) -> str:
        return (
            f"<WorkspaceMember workspace={self.workspace_id} "
            f"user={self.user_id} role={self.role}>"
        )
