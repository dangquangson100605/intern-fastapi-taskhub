"""Pydantic schemas for authentication, token lifecycle, and password management."""

from pydantic import EmailStr, Field, field_validator

from app.core.constants import (
    BEARER_TOKEN_TYPE,
    USER_EMAIL_MAX_LENGTH,
    USER_PASSWORD_MAX_LENGTH,
    USER_PASSWORD_MIN_LENGTH,
)
from app.schemas.base import BaseSchema, RawPassword, validate_password_bytes
from app.schemas.user import UserCreate


class RegisterRequest(UserCreate):
    """Schema for public self-registration without role selection."""


class LoginRequest(BaseSchema):
    """Schema for email and password authentication."""

    email: EmailStr = Field(..., max_length=USER_EMAIL_MAX_LENGTH)
    password: RawPassword = Field(..., min_length=1, max_length=USER_PASSWORD_MAX_LENGTH)

    @field_validator("password")
    @classmethod
    def check_password_bytes(cls, value: str) -> str:
        """Reject passwords exceeding bcrypt's 72-byte limit with 422."""
        return validate_password_bytes(value)


class RefreshTokenRequest(BaseSchema):
    """Schema for requesting rotated access and refresh tokens."""

    refresh_token: str = Field(..., min_length=1)


class LogoutRequest(BaseSchema):
    """Optional request body for revoking an associated refresh token on logout."""

    refresh_token: str | None = Field(default=None, min_length=1)


class TokenResponse(BaseSchema):
    """Schema for issued JWT access and refresh token pair."""

    access_token: str
    refresh_token: str
    token_type: str = BEARER_TOKEN_TYPE
    expires_in: int


class ChangePasswordRequest(BaseSchema):
    """Schema for authenticated user password rotation."""

    current_password: RawPassword = Field(..., min_length=1, max_length=USER_PASSWORD_MAX_LENGTH)
    new_password: RawPassword = Field(
        ...,
        min_length=USER_PASSWORD_MIN_LENGTH,
        max_length=USER_PASSWORD_MAX_LENGTH,
    )

    @field_validator("current_password", "new_password")
    @classmethod
    def check_password_bytes(cls, value: str) -> str:
        """Ensure passwords fit within bcrypt's 72-byte UTF-8 limit."""
        return validate_password_bytes(value)
