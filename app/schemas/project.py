"""Pydantic schemas for Project entities."""

from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field, ValidationInfo, field_validator

from app.core.constants import PROJECT_NAME_MAX_LENGTH, PROJECT_NAME_MIN_LENGTH
from app.models.enums import ProjectStatus
from app.schemas.base import BaseSchema, validate_non_null


class ProjectCreate(BaseSchema):
    """Schema for creating a project inside a workspace."""

    name: str = Field(
        ...,
        min_length=PROJECT_NAME_MIN_LENGTH,
        max_length=PROJECT_NAME_MAX_LENGTH,
    )
    description: str | None = Field(default=None)


class ProjectUpdate(BaseSchema):
    """Schema for modifying existing project details."""

    name: str | None = Field(
        default=None,
        min_length=PROJECT_NAME_MIN_LENGTH,
        max_length=PROJECT_NAME_MAX_LENGTH,
    )
    description: str | None = Field(default=None)

    @field_validator("name")
    @classmethod
    def check_non_null(cls, value: Any, info: ValidationInfo) -> Any:
        """Reject explicit null on partial name update."""
        return validate_non_null(value, info)


class ProjectResponse(BaseSchema):
    """Schema for project responses."""

    id: int
    workspace_id: int
    name: str
    description: str | None = None
    status: ProjectStatus
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
