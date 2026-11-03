"""Pydantic schemas for User request/response validation."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserRole

# --- Request Schemas ---


class UserCreate(BaseModel):
    """Schema for user registration."""

    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)


class UserUpdate(BaseModel):
    """Schema for updating user profile (partial update)."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None


class ChangePassword(BaseModel):
    """Schema for changing password."""

    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)


# --- Response Schemas ---


class UserResponse(BaseModel):
    """Schema for user data in API responses."""

    id: int
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
