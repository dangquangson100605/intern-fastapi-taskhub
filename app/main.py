"""TaskHub — FastAPI application entry point.

Creates the FastAPI app instance, registers routers, exception handlers,
and lifespan events (startup/shutdown).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy.exc import IntegrityError

from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.core.database import async_engine
from app.core.exceptions import AppException, app_exception_handler, generic_exception_handler
from app.core.messages import (
    ERROR_CANNOT_DELETE_USER_WITH_DEPENDENCIES,
    ERROR_DATABASE_INTEGRITY,
    ERROR_FOREIGN_KEY_VIOLATION,
    ERROR_RESOURCE_ALREADY_EXISTS,
)
from app.core.redis import close_redis, ping_redis

settings = get_settings()

openapi_tags = [
    {
        "name": "Auth",
        "description": "User registration, authentication, JWT tokens, and token revoking.",
    },
    {
        "name": "Users",
        "description": "User profile retrieval, updates, and administrative user controls.",
    },
    {
        "name": "Workspaces",
        "description": "Workspace management and multi-tenant membership role administration.",
    },
    {
        "name": "Projects",
        "description": "Project creation, status transitions, and workspace scoping.",
    },
    {
        "name": "Tasks",
        "description": "Task lifecycle, assignment, status transitions, search/filtering, and background notifications.",
    },
    {
        "name": "Labels",
        "description": "Project label definitions and task-label associations.",
    },
    {
        "name": "Comments",
        "description": "Discussion comments on tasks with author tracking.",
    },
]

app_description = (
    "**TaskHub** — A production-ready Task Management API.\n\n"
    "### Key Architecture & Features:\n"
    "- **Multi-tenant RBAC**: Admin, Workspace Owner, Editor, and Viewer permission levels.\n"
    "- **JWT Authentication**: Access and refresh tokens with Redis blacklist token revoking.\n"
    "- **Advanced Querying**: Search, multi-field filtering, sorting, and pagination.\n"
    "- **Performance & Caching**: Project-versioned Redis caching with automatic invalidation.\n"
    "- **Background Tasks**: Non-blocking notifications for task assignments and status transitions.\n"
    "- **Standardized Error Responses**: Uniform JSON error envelopes across all endpoints.\n"
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: runs on startup and shutdown."""
    logger.info("🚀 Starting TaskHub v{}", settings.APP_VERSION)
    logger.info("📦 Database: {}", settings.DB_HOST)
    logger.info("🔴 Redis: {}:{}", settings.REDIS_HOST, settings.REDIS_PORT)
    await ping_redis()
    yield
    logger.info("🛑 Shutting down TaskHub")
    await close_redis()
    await async_engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=app_description,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
    contact={
        "name": "TaskHub API Support",
        "email": "support@taskhub.io",
    },
    license_info={
        "name": "MIT",
        "identifier": "MIT",
    },
    openapi_tags=openapi_tags,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Format 422 validation errors to match the uniform API error format."""
    details = jsonable_encoder(exc.errors()) if isinstance(exc, RequestValidationError) else []
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "error": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "path": request.url.path,
            "details": details,
        },
    )


async def integrity_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle database integrity errors distinguishing duplicate entries and foreign keys."""
    orig_error = getattr(exc, "orig", None)
    logger.warning("Database integrity error: {}", orig_error or str(exc))

    orig_msg = str(orig_error or exc).lower()
    if "duplicate" in orig_msg or "unique" in orig_msg or "1062" in orig_msg:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": "CONFLICT",
                "message": ERROR_RESOURCE_ALREADY_EXISTS,
                "path": request.url.path,
            },
        )
    if "1451" in orig_msg or "cannot delete or update a parent row" in orig_msg:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": "CONFLICT",
                "message": ERROR_CANNOT_DELETE_USER_WITH_DEPENDENCIES,
                "path": request.url.path,
            },
        )
    if (
        "foreign key" in orig_msg
        or "1452" in orig_msg
        or "cannot add or update a child row" in orig_msg
    ):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": "INVALID_REFERENCE",
                "message": ERROR_FOREIGN_KEY_VIOLATION,
                "path": request.url.path,
            },
        )

    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": "INTEGRITY_ERROR",
            "message": ERROR_DATABASE_INTEGRITY,
            "path": request.url.path,
        },
    )


app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(IntegrityError, integrity_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

app.include_router(api_v1_router)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """Simple health check endpoint."""
    return {"status": "healthy", "app": settings.APP_NAME, "version": settings.APP_VERSION}
