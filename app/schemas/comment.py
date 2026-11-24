"""Pydantic schemas for Comment entities."""

from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field, ValidationInfo, field_validator

from app.core.constants import (
    COMMENT_CONTENT_MAX_LENGTH,
    COMMENT_CONTENT_MIN_LENGTH,
)
from app.schemas.base import BaseSchema, validate_non_null


class CommentAuthorResponse(BaseSchema):
    """Minimal user representation for comment author."""

    id: int
    email: str
    full_name: str

    model_config = ConfigDict(from_attributes=True)


class CommentCreate(BaseSchema):
    """Schema for creating a comment."""

    content: str = Field(
        ...,
        min_length=COMMENT_CONTENT_MIN_LENGTH,
        max_length=COMMENT_CONTENT_MAX_LENGTH,
    )


class CommentUpdate(BaseSchema):
    """Schema for updating a comment."""

    content: str = Field(
        ...,
        min_length=COMMENT_CONTENT_MIN_LENGTH,
        max_length=COMMENT_CONTENT_MAX_LENGTH,
    )

    @field_validator("content")
    @classmethod
    def check_non_null(cls, value: Any, info: ValidationInfo) -> Any:
        """Reject explicit null on fields that cannot be null."""
        return validate_non_null(value, info)


class CommentResponse(BaseSchema):
    """Schema for comment response."""

    id: int
    task_id: int
    author_id: int
    content: str
    created_at: datetime
    author: CommentAuthorResponse | None = None

    model_config = ConfigDict(from_attributes=True)
