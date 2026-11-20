"""Shared/common Pydantic schemas used across multiple modules."""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from app.core.constants import DEFAULT_LIMIT, DEFAULT_PAGE, MAX_LIMIT

T = TypeVar("T")


class PaginationParams(BaseModel):
    """Re-usable pagination query parameters."""

    page: int = Field(default=DEFAULT_PAGE, ge=1, description="Page number (1-based)")
    limit: int = Field(
        default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Number of items per page"
    )

    @property
    def offset(self) -> int:
        """Calculate SQL query row offset."""
        return (self.page - 1) * self.limit


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
