"""Label and TaskLabel SQLAlchemy models."""

from typing import TYPE_CHECKING

from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.task import Task

task_labels = Table(
    "task_labels",
    Base.metadata,
    Column("task_id", ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("label_id", ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True),
)


class Label(Base):
    """A label belongs to a project and can be attached to tasks."""

    __tablename__ = "labels"

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str] = mapped_column(String(7), default="#3B82F6", nullable=False)

    project: Mapped["Project"] = relationship(
        back_populates="labels",
        lazy="selectin",
    )
    tasks: Mapped[list["Task"]] = relationship(
        secondary=task_labels,
        back_populates="labels",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Label id={self.id} name={self.name!r}>"
