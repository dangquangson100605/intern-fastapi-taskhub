"""Pydantic schemas for Task entities and status updates."""

from datetime import UTC, datetime
from typing import Any

from pydantic import ConfigDict, Field, ValidationInfo, field_validator

from app.core.constants import TASK_TITLE_MAX_LENGTH, TASK_TITLE_MIN_LENGTH
from app.core.messages import ERROR_DUE_DATE_IN_PAST
from app.models.enums import TaskPriority, TaskStatus
from app.schemas.base import BaseSchema, validate_non_null


class TaskCreate(BaseSchema):
    """Schema for task creation. Status is always TODO and created_by is derived from token."""

    title: str = Field(
        ...,
        min_length=TASK_TITLE_MIN_LENGTH,
        max_length=TASK_TITLE_MAX_LENGTH,
    )
    description: str | None = Field(default=None)
    priority: TaskPriority = Field(default=TaskPriority.MEDIUM)
    assignee_id: int | None = Field(default=None, ge=1)
    due_date: datetime | None = Field(default=None)

    @field_validator("due_date")
    @classmethod
    def validate_due_date(cls, value: datetime | None) -> datetime | None:
        """Reject due dates positioned in the past."""
        if value is not None:
            now_utc = datetime.now(UTC)
            val_utc = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
            if val_utc < now_utc:
                raise ValueError(ERROR_DUE_DATE_IN_PAST)
        return value


class TaskUpdate(BaseSchema):
    """Schema for updating task attributes."""

    title: str | None = Field(
        default=None,
        min_length=TASK_TITLE_MIN_LENGTH,
        max_length=TASK_TITLE_MAX_LENGTH,
    )
    description: str | None = Field(default=None)
    priority: TaskPriority | None = Field(default=None)
    status: TaskStatus | None = Field(default=None)
    assignee_id: int | None = Field(default=None, ge=1)
    due_date: datetime | None = Field(default=None)

    @field_validator("title")
    @classmethod
    def check_non_null(cls, value: Any, info: ValidationInfo) -> Any:
        """Reject explicit null on partial title update."""
        return validate_non_null(value, info)

    @field_validator("due_date")
    @classmethod
    def validate_due_date(cls, value: datetime | None) -> datetime | None:
        """Reject due dates positioned in the past."""
        if value is not None:
            now_utc = datetime.now(UTC)
            val_utc = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
            if val_utc < now_utc:
                raise ValueError(ERROR_DUE_DATE_IN_PAST)
        return value


class TaskStatusUpdate(BaseSchema):
    """Schema for fast status transitions."""

    status: TaskStatus = Field(...)


class TaskUserResponse(BaseSchema):
    """Minimal user representation for task assignee or creator."""

    id: int
    email: str
    full_name: str

    model_config = ConfigDict(from_attributes=True)


class TaskResponse(BaseSchema):
    """Schema for returning task details."""

    id: int
    project_id: int
    assignee_id: int | None = None
    created_by: int
    title: str
    description: str | None = None
    status: TaskStatus
    priority: TaskPriority
    due_date: datetime | None = None
    created_at: datetime
    assignee: TaskUserResponse | None = None
    creator: TaskUserResponse | None = None

    model_config = ConfigDict(from_attributes=True)
