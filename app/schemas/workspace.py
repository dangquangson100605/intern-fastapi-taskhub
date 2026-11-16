"""Pydantic schemas for workspaces and workspace membership."""

from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field, ValidationInfo, field_validator

from app.core.constants import WORKSPACE_NAME_MAX_LENGTH, WORKSPACE_NAME_MIN_LENGTH
from app.core.messages import ERROR_CANNOT_ASSIGN_OWNER_ROLE
from app.models.enums import WorkspaceRole
from app.schemas.base import BaseSchema, validate_non_null


class WorkspaceCreate(BaseSchema):
    """Schema for creating a new workspace."""

    name: str = Field(
        ...,
        min_length=WORKSPACE_NAME_MIN_LENGTH,
        max_length=WORKSPACE_NAME_MAX_LENGTH,
    )


class WorkspaceUpdate(BaseSchema):
    """Schema for updating workspace properties."""

    name: str | None = Field(
        default=None,
        min_length=WORKSPACE_NAME_MIN_LENGTH,
        max_length=WORKSPACE_NAME_MAX_LENGTH,
    )

    @field_validator("name")
    @classmethod
    def check_non_null(cls, value: Any, info: ValidationInfo) -> Any:
        """Reject explicit null on partial updates."""
        return validate_non_null(value, info)


class WorkspaceResponse(BaseSchema):
    """Schema for returning workspace details."""

    id: int
    name: str
    owner_id: int
    role: WorkspaceRole | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkspaceMemberAdd(BaseSchema):
    """Schema for adding a member to a workspace."""

    user_id: int = Field(..., ge=1)
    role: WorkspaceRole = Field(default=WorkspaceRole.VIEWER)

    @field_validator("role")
    @classmethod
    def reject_owner_role(cls, value: WorkspaceRole) -> WorkspaceRole:
        """Prevent direct assignment of OWNER role via member endpoints."""
        if value == WorkspaceRole.OWNER:
            raise ValueError(ERROR_CANNOT_ASSIGN_OWNER_ROLE)
        return value


class WorkspaceMemberUpdate(BaseSchema):
    """Schema for updating a member's role within a workspace."""

    role: WorkspaceRole = Field(...)

    @field_validator("role")
    @classmethod
    def reject_owner_role(cls, value: WorkspaceRole) -> WorkspaceRole:
        """Prevent elevating to OWNER role via role update endpoint."""
        if value == WorkspaceRole.OWNER:
            raise ValueError(ERROR_CANNOT_ASSIGN_OWNER_ROLE)
        return value


class WorkspaceMemberUserResponse(BaseSchema):
    """Minimal user representation embedded inside a member record."""

    id: int
    email: str
    full_name: str

    model_config = ConfigDict(from_attributes=True)


class WorkspaceMemberResponse(BaseSchema):
    """Schema representing a member in a workspace."""

    id: int
    workspace_id: int
    user_id: int
    role: WorkspaceRole
    created_at: datetime
    user: WorkspaceMemberUserResponse | None = None

    model_config = ConfigDict(from_attributes=True)

