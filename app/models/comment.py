"""Comment SQLAlchemy model."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.task import Task
    from app.models.user import User


class Comment(Base):
    """A comment on a task, authored by a user."""

    __tablename__ = "comments"

    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    task: Mapped["Task"] = relationship(
        back_populates="comments",
        lazy="selectin",
    )
    author: Mapped["User"] = relationship(lazy="selectin")

    def __repr__(self) -> str:
        return f"<Comment id={self.id} task={self.task_id}>"
