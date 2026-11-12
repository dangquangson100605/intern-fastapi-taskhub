"""Custom exception classes and global exception handlers.

Provides a consistent JSON error response format across the entire API.
"""

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from loguru import logger

from app.core.messages import (
    ERROR_BAD_REQUEST,
    ERROR_INTERNAL_SERVER,
    ERROR_NOT_AUTHENTICATED,
    ERROR_PERMISSION_DENIED,
    ERROR_REDIS_UNAVAILABLE,
    ERROR_RESOURCE_ALREADY_EXISTS,
    ERROR_RESOURCE_NOT_FOUND,
    ERROR_RESOURCE_WITH_ID_NOT_FOUND,
    ERROR_USER_NOT_FOUND,
)


class AppException(HTTPException):
    """Base application exception with a machine-readable error code."""

    def __init__(
        self,
        status_code: int,
        message: str,
        error_code: str = "APP_ERROR",
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.message = message
        self.error_code = error_code


class NotFoundException(AppException):
    """Resource not found (404)."""

    def __init__(self, resource: str = "Resource", resource_id: int | str = "") -> None:
        if resource.lower() == "user" and resource_id:
            detail = ERROR_USER_NOT_FOUND.format(user_id=resource_id)
        elif resource_id:
            detail = ERROR_RESOURCE_WITH_ID_NOT_FOUND.format(
                resource=resource, resource_id=resource_id
            )
        else:
            detail = ERROR_RESOURCE_NOT_FOUND.format(resource=resource)

        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            message=detail,
            error_code="NOT_FOUND",
        )


class BadRequestException(AppException):
    """Invalid request (400)."""

    def __init__(self, message: str = ERROR_BAD_REQUEST) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=message,
            error_code="BAD_REQUEST",
        )


class ForbiddenException(AppException):
    """Insufficient permissions (403)."""

    def __init__(self, message: str = ERROR_PERMISSION_DENIED) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            message=message,
            error_code="FORBIDDEN",
        )


class UnauthorizedException(AppException):
    """Authentication required or failed (401)."""

    def __init__(
        self,
        message: str = ERROR_NOT_AUTHENTICATED,
        headers: dict[str, str] | None = None,
    ) -> None:
        auth_headers = headers if headers is not None else {"WWW-Authenticate": "Bearer"}
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=message,
            error_code="UNAUTHORIZED",
            headers=auth_headers,
        )


class ConflictException(AppException):
    """Resource conflict, e.g. duplicate email (409)."""

    def __init__(self, message: str = ERROR_RESOURCE_ALREADY_EXISTS) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            message=message,
            error_code="CONFLICT",
        )


class ServiceUnavailableException(AppException):
    """Dependent infrastructure service unavailable (503)."""

    def __init__(self, message: str = ERROR_REDIS_UNAVAILABLE) -> None:
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message=message,
            error_code="SERVICE_UNAVAILABLE",
        )


async def app_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle custom AppException and return consistent JSON."""
    if isinstance(exc, AppException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.error_code,
                "message": exc.message,
                "path": str(request.url),
            },
            headers=exc.headers,
        )
    return await generic_exception_handler(request, exc)


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions."""
    logger.exception("Unhandled server exception: {}", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "INTERNAL_ERROR",
            "message": ERROR_INTERNAL_SERVER,
            "path": str(request.url),
        },
    )
