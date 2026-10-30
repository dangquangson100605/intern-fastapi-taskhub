"""Task SQLAlchemy model."""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TaskStatus(str, enum.Enum):
    """Task workflow statuses."""

    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    IN_REVIEW = "IN_REVIEW"
    DONE = "DONE"


class TaskPriority(str, enum.Enum):
    """Task priority levels."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class Task(Base):
    """A task belongs to a project, can be assigned to a user."""

    __tablename__ = "tasks"

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), default=TaskStatus.TODO, nullable=False
    )
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority), default=TaskPriority.MEDIUM, nullable=False
    )
    due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # --- Relationships ---
    project: Mapped["Project"] = relationship(  # noqa: F821
        back_populates="tasks",
        lazy="selectin",
    )
    assignee: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[assignee_id],
        lazy="selectin",
    )
    creator: Mapped["User"] = relationship(  # noqa: F821
        foreign_keys=[created_by],
        lazy="selectin",
    )
    labels: Mapped[list["Label"]] = relationship(  # noqa: F821
        secondary="task_labels",
        back_populates="tasks",
        lazy="selectin",
    )
    comments: Mapped[list["Comment"]] = relationship(  # noqa: F821
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Task id={self.id} title={self.title!r}>"
