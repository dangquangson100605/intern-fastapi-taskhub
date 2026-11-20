"""Pydantic schemas for Comment entities."""

from datetime import datetime

from pydantic import ConfigDict, Field

from app.core.constants import (
    COMMENT_CONTENT_MAX_LENGTH,
    COMMENT_CONTENT_MIN_LENGTH,
)
from app.schemas.base import BaseSchema


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


class CommentResponse(BaseSchema):
    """Schema for comment response."""

    id: int
    task_id: int
    author_id: int
    content: str
    created_at: datetime
    author: CommentAuthorResponse | None = None

    model_config = ConfigDict(from_attributes=True)
