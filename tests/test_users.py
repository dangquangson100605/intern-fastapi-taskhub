"""Unit tests for User endpoints."""

from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.dependencies import get_user_service
from app.core.exceptions import ConflictException
from app.main import app
from app.services.user import UserService


@pytest.mark.anyio
async def test_create_user_password_exceeds_72_bytes_returns_422() -> None:
    """Password longer than 72 bytes must be rejected with 422 Unprocessable Entity."""
    long_password = "a" * 73
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/api/v1/users",
            json={
                "email": "test_long_pwd@example.com",
                "full_name": "Test Long Password",
                "password": long_password,
            },
        )
    assert response.status_code == 422
    data = response.json()
    assert data["error"] == "VALIDATION_ERROR"


@pytest.mark.anyio
async def test_create_user_duplicate_email_returns_409() -> None:
    """Registering an existing email must return 409 Conflict."""
    mock_service = AsyncMock(spec=UserService)
    mock_service.create_user.side_effect = ConflictException(
        "Email 'dup@example.com' is already registered"
    )

    app.dependency_overrides[get_user_service] = lambda: mock_service

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/users",
                json={
                    "email": "dup@example.com",
                    "full_name": "Duplicate User",
                    "password": "valid_password_123",
                },
            )
        assert response.status_code == 409
        data = response.json()
        assert data["error"] == "CONFLICT"
    finally:
        app.dependency_overrides.clear()
