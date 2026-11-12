"""Pydantic schemas for User request/response validation."""

from datetime import datetime
from typing import Any

from pydantic import ConfigDict, EmailStr, Field, ValidationInfo, field_validator

from app.core.constants import (
    USER_EMAIL_MAX_LENGTH,
    USER_FULL_NAME_MAX_LENGTH,
    USER_FULL_NAME_MIN_LENGTH,
    USER_PASSWORD_MAX_LENGTH,
    USER_PASSWORD_MIN_LENGTH,
)
from app.models.enums import UserRole
from app.schemas.base import BaseSchema, RawPassword, validate_non_null, validate_password_bytes


class UserCreate(BaseSchema):
    """Base schema for creating a user account."""

    email: EmailStr = Field(..., max_length=USER_EMAIL_MAX_LENGTH)
    full_name: str = Field(
        ...,
        min_length=USER_FULL_NAME_MIN_LENGTH,
        max_length=USER_FULL_NAME_MAX_LENGTH,
    )
    password: RawPassword = Field(
        ...,
        min_length=USER_PASSWORD_MIN_LENGTH,
        max_length=USER_PASSWORD_MAX_LENGTH,
    )

    @field_validator("password")
    @classmethod
    def check_password_bytes(cls, value: str) -> str:
        """Ensure password fits within bcrypt's 72-byte UTF-8 limit."""
        return validate_password_bytes(value)


class AdminUserCreate(UserCreate):
    """Schema for admin user creation allowing optional role assignment."""

    role: UserRole = UserRole.MEMBER


class UserUpdate(BaseSchema):
    """Schema for updating own user profile (partial update)."""

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
        return validate_non_null(value, info)


class AdminUserUpdate(UserUpdate):
    """Schema for admin updates to a user's profile, role, or active status."""

    role: UserRole | None = None
    is_active: bool | None = None

    @field_validator("role", "is_active", mode="before")
    @classmethod
    def validate_admin_non_nullable_fields(cls, value: Any, info: ValidationInfo) -> Any:
        """Prevent explicit null values on role or is_active."""
        return validate_non_null(value, info)


class UserResponse(BaseSchema):
    """Schema for user data in API responses."""

    id: int
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)
