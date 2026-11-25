"""Application constants: validation constraints, security settings, and defaults."""

from app.core.enums import WorkspaceRole

RESOURCE_USER: str = "User"
RESOURCE_WORKSPACE: str = "Workspace"
RESOURCE_WORKSPACE_MEMBER: str = "Workspace member"
RESOURCE_PROJECT: str = "Project"
RESOURCE_TASK: str = "Task"
RESOURCE_LABEL: str = "Label"
RESOURCE_COMMENT: str = "Comment"

DEFAULT_PAGE: int = 1
DEFAULT_LIMIT: int = 20
MAX_LIMIT: int = 100

USER_FULL_NAME_MIN_LENGTH: int = 1
USER_FULL_NAME_MAX_LENGTH: int = 255
USER_PASSWORD_MIN_LENGTH: int = 8
USER_PASSWORD_MAX_LENGTH: int = 72
USER_EMAIL_MAX_LENGTH: int = 255
USER_PASSWORD_HASH_MAX_LENGTH: int = 255

JWT_SECRET_KEY_MIN_LENGTH: int = 32
DEFAULT_JWT_ALGORITHM: str = "HS256"
BEARER_TOKEN_TYPE: str = "bearer"
TOKEN_JTI_MAX_LENGTH: int = 36
REDIS_BLACKLIST_PREFIX: str = "blacklist:token:"
REDIS_SOCKET_TIMEOUT: float = 3.0
REDIS_SOCKET_CONNECT_TIMEOUT: float = 3.0
INSECURE_JWT_SECRET_PLACEHOLDERS: tuple[str, ...] = (
    "CHANGE_ME",
    "your-super-secret-key-change-in-production",
)

WORKSPACE_NAME_MIN_LENGTH: int = 1
WORKSPACE_NAME_MAX_LENGTH: int = 255

WORKSPACE_WRITE_ROLES: frozenset[WorkspaceRole] = frozenset(
    {
        WorkspaceRole.OWNER,
        WorkspaceRole.EDITOR,
    }
)

PROJECT_NAME_MIN_LENGTH: int = 1
PROJECT_NAME_MAX_LENGTH: int = 255
DESCRIPTION_MAX_LENGTH: int = 10_000

TASK_TITLE_MIN_LENGTH: int = 1
TASK_TITLE_MAX_LENGTH: int = 500

LABEL_NAME_MIN_LENGTH: int = 1
LABEL_NAME_MAX_LENGTH: int = 50
LABEL_COLOR_MAX_LENGTH: int = 7
DEFAULT_LABEL_COLOR: str = "#3B82F6"
HEX_COLOR_REGEX: str = r"^#(?:[0-9a-fA-F]{3}){1,2}$"

COMMENT_CONTENT_MIN_LENGTH: int = 1
COMMENT_CONTENT_MAX_LENGTH: int = 5_000

MAX_SEARCH_KEYWORD_LENGTH: int = 255
REDIS_PROJECT_TASKS_CACHE_PREFIX: str = "cache:project"
