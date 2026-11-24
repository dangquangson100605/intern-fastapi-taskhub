"""Pydantic schemas for Label entities and task association."""

from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field, ValidationInfo, field_validator

from app.core.constants import (
    DEFAULT_LABEL_COLOR,
    HEX_COLOR_REGEX,
    LABEL_COLOR_MAX_LENGTH,
    LABEL_NAME_MAX_LENGTH,
    LABEL_NAME_MIN_LENGTH,
)
from app.schemas.base import BaseSchema, validate_non_null


class LabelCreate(BaseSchema):
    """Schema for creating a label."""

    name: str = Field(
        ...,
        min_length=LABEL_NAME_MIN_LENGTH,
        max_length=LABEL_NAME_MAX_LENGTH,
    )
    color: str = Field(
        default=DEFAULT_LABEL_COLOR,
        max_length=LABEL_COLOR_MAX_LENGTH,
        pattern=HEX_COLOR_REGEX,
    )


class LabelUpdate(BaseSchema):
    """Schema for updating label name or color."""

    name: str | None = Field(
        default=None,
        min_length=LABEL_NAME_MIN_LENGTH,
        max_length=LABEL_NAME_MAX_LENGTH,
    )
    color: str | None = Field(
        default=None,
        max_length=LABEL_COLOR_MAX_LENGTH,
        pattern=HEX_COLOR_REGEX,
    )

    @field_validator("name", "color")
    @classmethod
    def check_non_null(cls, value: Any, info: ValidationInfo) -> Any:
        """Reject explicit null on fields that cannot be null."""
        return validate_non_null(value, info)


class LabelResponse(BaseSchema):
    """Schema for label response."""

    id: int
    project_id: int
    name: str
    color: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
