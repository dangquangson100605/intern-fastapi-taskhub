"""TaskHub — FastAPI application entry point.

Creates the FastAPI app instance, registers routers, exception handlers,
and lifespan events (startup/shutdown).
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.core.exceptions import AppException, app_exception_handler, generic_exception_handler

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: runs on startup and shutdown."""
    logger.info("🚀 Starting TaskHub v{}", settings.APP_VERSION)
    logger.info("📦 Database: {}", settings.DB_HOST)
    logger.info("🔴 Redis: {}:{}", settings.REDIS_HOST, settings.REDIS_PORT)
    yield
    logger.info("🛑 Shutting down TaskHub")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "**TaskHub** — A comprehensive Task Management API.\n\n"
        "Manage workspaces, projects, tasks, labels, and comments "
        "with role-based access control."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

app.include_router(api_v1_router)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """Simple health check endpoint."""
    return {"status": "healthy", "app": settings.APP_NAME, "version": settings.APP_VERSION}
