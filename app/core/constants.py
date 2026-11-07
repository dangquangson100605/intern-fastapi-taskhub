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

ERROR_EMAIL_ALREADY_REGISTERED: str = "Email '{email}' is already registered"
ERROR_EMAIL_ALREADY_IN_USE: str = "Email '{email}' is already in use"
ERROR_USER_NOT_FOUND: str = "User with id '{user_id}' not found"
ERROR_FIELD_CANNOT_BE_NULL: str = "Field '{field}' cannot be null"
ERROR_DATABASE_INTEGRITY: str = "Database constraint violation (duplicate entry or invalid reference)"

SUCCESS_USER_DELETED: str = "User deleted successfully"
