"""Project SQLAlchemy model."""

from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import PROJECT_NAME_MAX_LENGTH
from app.core.database import Base
from app.models.enums import ProjectStatus

if TYPE_CHECKING:
    from app.models.label import Label
    from app.models.task import Task
    from app.models.workspace import Workspace


class Project(Base):
    """A project belongs to a workspace and contains tasks."""

    __tablename__ = "projects"

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(PROJECT_NAME_MAX_LENGTH),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, native_enum=False, create_constraint=True),
        server_default=ProjectStatus.ACTIVE.value,
        default=ProjectStatus.ACTIVE,
        nullable=False,
    )

    workspace: Mapped["Workspace"] = relationship(
        back_populates="projects",
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    labels: Mapped[list["Label"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} name={self.name!r}>"
