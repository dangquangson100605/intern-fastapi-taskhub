"""Shared authorization and security policies across services."""

from app.core.constants import WORKSPACE_WRITE_ROLES
from app.core.exceptions import AppException, ConflictException, ForbiddenException
from app.core.messages import ERROR_PERMISSION_DENIED, ERROR_PROJECT_ARCHIVED
from app.models.enums import ProjectStatus, WorkspaceRole
from app.models.project import Project


def ensure_write_access(
    role: WorkspaceRole | None,
    project: Project,
    is_admin: bool,
    not_found_exc: AppException,
    *,
    require_active: bool = True,
) -> None:
    """Ensure that the caller has write access to the workspace resource and project is active."""
    if not is_admin and role is None:
        raise not_found_exc
    if not is_admin and role not in WORKSPACE_WRITE_ROLES:
        raise ForbiddenException(ERROR_PERMISSION_DENIED)
    if require_active and project.status == ProjectStatus.ARCHIVED:
        raise ConflictException(ERROR_PROJECT_ARCHIVED)
