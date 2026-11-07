"""System and domain enumeration types."""

import enum


class UserRole(str, enum.Enum):
    """System-wide user roles."""

    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class WorkspaceRole(str, enum.Enum):
    """Roles within a specific workspace."""

    OWNER = "OWNER"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"


class ProjectStatus(str, enum.Enum):
    """Project lifecycle statuses."""

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class TaskStatus(str, enum.Enum):
    """Task workflow statuses."""

    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    IN_REVIEW = "IN_REVIEW"
    DONE = "DONE"


class TaskPriority(str, enum.Enum):
    """Task priority levels."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"

