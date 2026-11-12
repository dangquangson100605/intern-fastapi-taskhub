"""Centralized user-facing error and success message constants."""

ERROR_BAD_REQUEST: str = "Bad request"
ERROR_PERMISSION_DENIED: str = "Permission denied"
ERROR_NOT_AUTHENTICATED: str = "Not authenticated"
ERROR_INVALID_CREDENTIALS: str = "Incorrect email or password"
ERROR_INACTIVE_USER: str = "Inactive user"
ERROR_INVALID_TOKEN: str = "Invalid or expired token"
ERROR_INVALID_TOKEN_TYPE: str = "Invalid token type"
ERROR_TOKEN_REVOKED: str = "Token has been revoked"
ERROR_REFRESH_TOKEN_REUSED: str = "Refresh token reuse detected; all sessions have been revoked"
ERROR_INCORRECT_CURRENT_PASSWORD: str = "Current password is incorrect"
ERROR_NEW_PASSWORD_SAME_AS_OLD: str = "New password must be different from current password"
ERROR_PASSWORD_TOO_LONG_BYTES: str = "Password must not exceed {max_bytes} bytes when UTF-8 encoded"

ERROR_RESOURCE_ALREADY_EXISTS: str = "Resource already exists"
ERROR_RESOURCE_NOT_FOUND: str = "{resource} not found"
ERROR_RESOURCE_WITH_ID_NOT_FOUND: str = "{resource} with id '{resource_id}' not found"
ERROR_USER_NOT_FOUND: str = "User with id '{user_id}' not found"
ERROR_EMAIL_ALREADY_REGISTERED: str = "Email '{email}' is already registered"
ERROR_EMAIL_ALREADY_IN_USE: str = "Email '{email}' is already in use"
ERROR_FIELD_CANNOT_BE_NULL: str = "Field '{field}' cannot be null"
ERROR_CANNOT_DELETE_SELF: str = "Cannot delete your own account"
ERROR_CANNOT_REMOVE_LAST_ADMIN: str = "Cannot remove or deactivate the last active admin"
ERROR_CANNOT_DELETE_USER_WITH_DEPENDENCIES: str = (
    "Cannot delete user because they have associated records"
)
ERROR_DATABASE_INTEGRITY: str = (
    "Database constraint violation (duplicate entry or invalid reference)"
)
ERROR_FOREIGN_KEY_VIOLATION: str = "Referenced resource does not exist"
ERROR_INTERNAL_SERVER: str = "An unexpected error occurred"
ERROR_REDIS_UNAVAILABLE: str = "Authentication cache service is temporarily unavailable"
ERROR_INSECURE_JWT_SECRET: str = "JWT_SECRET_KEY must not use a placeholder value"

SUCCESS_USER_DELETED: str = "User deleted successfully"
SUCCESS_LOGOUT: str = "Logged out successfully"
SUCCESS_PASSWORD_CHANGED: str = "Password updated successfully"
