"""Application constants: validation constraints, error messages, and system defaults."""

USER_FULL_NAME_MIN_LENGTH: int = 1
USER_FULL_NAME_MAX_LENGTH: int = 255
USER_PASSWORD_MIN_LENGTH: int = 8
USER_PASSWORD_MAX_LENGTH: int = 128
USER_EMAIL_MAX_LENGTH: int = 255

ERROR_EMAIL_ALREADY_REGISTERED: str = "Email '{email}' is already registered"
ERROR_EMAIL_ALREADY_IN_USE: str = "Email '{email}' is already in use"
ERROR_USER_NOT_FOUND: str = "User with id '{user_id}' not found"
ERROR_FIELD_CANNOT_BE_NULL: str = "Field '{field}' cannot be null"

SUCCESS_USER_DELETED: str = "User deleted successfully"

