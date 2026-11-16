"""System and domain enumeration types."""

import enum


class UserRole(enum.StrEnum):
    """System-wide user roles."""

    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class WorkspaceRole(enum.StrEnum):
    """Roles within a specific workspace."""

    OWNER = "OWNER"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"


class ProjectStatus(enum.StrEnum):
    """Project lifecycle statuses."""

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class TaskStatus(enum.StrEnum):
    """Task workflow statuses."""

    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    IN_REVIEW = "IN_REVIEW"
    DONE = "DONE"


class TaskPriority(enum.StrEnum):
    """Task priority levels."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class TokenType(enum.StrEnum):
    """JWT token purpose types."""

    ACCESS = "access"
    REFRESH = "refresh"
