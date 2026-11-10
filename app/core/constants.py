"""Application constants: validation constraints, error messages, and system defaults."""

DEFAULT_PAGE: int = 1
DEFAULT_LIMIT: int = 20
MAX_LIMIT: int = 100

USER_FULL_NAME_MIN_LENGTH: int = 1
USER_FULL_NAME_MAX_LENGTH: int = 255
USER_PASSWORD_MIN_LENGTH: int = 8
USER_PASSWORD_MAX_LENGTH: int = 128
USER_EMAIL_MAX_LENGTH: int = 255
USER_PASSWORD_HASH_MAX_LENGTH: int = 255

WORKSPACE_NAME_MIN_LENGTH: int = 1
WORKSPACE_NAME_MAX_LENGTH: int = 255

PROJECT_NAME_MIN_LENGTH: int = 1
PROJECT_NAME_MAX_LENGTH: int = 255

TASK_TITLE_MIN_LENGTH: int = 1
TASK_TITLE_MAX_LENGTH: int = 500

LABEL_NAME_MIN_LENGTH: int = 1
LABEL_NAME_MAX_LENGTH: int = 100
LABEL_COLOR_MAX_LENGTH: int = 7

ERROR_BAD_REQUEST: str = "Bad request"
ERROR_PERMISSION_DENIED: str = "Permission denied"
ERROR_NOT_AUTHENTICATED: str = "Not authenticated"
ERROR_RESOURCE_ALREADY_EXISTS: str = "Resource already exists"
ERROR_RESOURCE_NOT_FOUND: str = "{resource} not found"
ERROR_RESOURCE_WITH_ID_NOT_FOUND: str = "{resource} with id '{resource_id}' not found"
ERROR_USER_NOT_FOUND: str = "User with id '{user_id}' not found"
ERROR_EMAIL_ALREADY_REGISTERED: str = "Email '{email}' is already registered"
ERROR_EMAIL_ALREADY_IN_USE: str = "Email '{email}' is already in use"
ERROR_FIELD_CANNOT_BE_NULL: str = "Field '{field}' cannot be null"
ERROR_DATABASE_INTEGRITY: str = (
    "Database constraint violation (duplicate entry or invalid reference)"
)
ERROR_INTERNAL_SERVER: str = "An unexpected error occurred"

SUCCESS_USER_DELETED: str = "User deleted successfully"
