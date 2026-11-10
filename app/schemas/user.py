"""Pydantic schemas for User request/response validation."""

from datetime import datetime
from typing import Any

from pydantic import ConfigDict, EmailStr, Field, ValidationInfo, field_validator

from app.core.constants import (
    ERROR_FIELD_CANNOT_BE_NULL,
    USER_EMAIL_MAX_LENGTH,
    USER_FULL_NAME_MAX_LENGTH,
    USER_FULL_NAME_MIN_LENGTH,
    USER_PASSWORD_MAX_LENGTH,
    USER_PASSWORD_MIN_LENGTH,
)
from app.models.enums import UserRole
from app.schemas.base import BaseSchema


class UserCreate(BaseSchema):
    """Schema for user registration."""

    email: EmailStr = Field(..., max_length=USER_EMAIL_MAX_LENGTH)
    full_name: str = Field(
        ...,
        min_length=USER_FULL_NAME_MIN_LENGTH,
        max_length=USER_FULL_NAME_MAX_LENGTH,
    )
    password: str = Field(
        ...,
        min_length=USER_PASSWORD_MIN_LENGTH,
        max_length=USER_PASSWORD_MAX_LENGTH,
    )


class UserUpdate(BaseSchema):
    """Schema for updating user profile (partial update)."""

    full_name: str | None = Field(
        default=None,
        min_length=USER_FULL_NAME_MIN_LENGTH,
        max_length=USER_FULL_NAME_MAX_LENGTH,
    )
    email: EmailStr | None = Field(default=None, max_length=USER_EMAIL_MAX_LENGTH)

    @field_validator("full_name", "email", mode="before")
    @classmethod
    def validate_non_nullable_fields(cls, value: Any, info: ValidationInfo) -> Any:
        """Prevent client from sending explicit null for non-nullable fields."""
        if value is None:
            field_name = info.field_name or "field"
            raise ValueError(ERROR_FIELD_CANNOT_BE_NULL.format(field=field_name))
        return value


class UserResponse(BaseSchema):
    """Schema for user data in API responses."""

    id: int
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
