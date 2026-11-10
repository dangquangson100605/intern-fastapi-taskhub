"""Shared/common Pydantic schemas used across multiple modules."""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""

    items: list[T]
    total: int
    page: int
    limit: int
    total_pages: int

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    """Simple message response for success/error notifications."""

    message: str
    detail: str | None = None
