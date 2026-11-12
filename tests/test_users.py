"""Unit and RBAC tests for User endpoints."""

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    get_current_user,
    get_db,
    get_refresh_token_repository,
    get_token_blacklist,
    get_user_repository,
    get_user_service,
)
from app.core.exceptions import ConflictException
from app.core.redis import TokenBlacklistService
from app.core.security import create_access_token
from app.main import app
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.services.user import UserService


def _make_user(
    user_id: int,
    email: str,
    role: UserRole = UserRole.MEMBER,
    is_active: bool = True,
) -> User:
    """Construct an in-memory User instance for endpoint tests."""
    return User(
        id=user_id,
        email=email,
        full_name=f"User {user_id}",
        hashed_password="hashed_placeholder",
        role=role,
        is_active=is_active,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> Generator[None, None, None]:
    """Ensure FastAPI dependency overrides are reset around every test."""
    yield
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_create_user_as_admin_password_exceeds_72_bytes_returns_422() -> None:
    """Password longer than 72 bytes must be rejected with 422 Unprocessable Content."""
    admin = _make_user(1, "admin@example.com", role=UserRole.ADMIN)
    app.dependency_overrides[get_current_user] = lambda: admin

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
    assert response.json()["error"] == "VALIDATION_ERROR"


@pytest.mark.anyio
async def test_create_user_duplicate_email_returns_409() -> None:
    """Creating a user with an existing email must map IntegrityError to 409 Conflict."""
    admin = _make_user(1, "admin@example.com", role=UserRole.ADMIN)
    mock_session = AsyncMock(spec=AsyncSession)
    mock_user_repo = AsyncMock(spec=UserRepository)
    mock_user_repo.create.side_effect = IntegrityError(
        "INSERT INTO users ...",
        {},
        Exception("1062 (23000): Duplicate entry 'dup@example.com' for key 'users.ix_users_email'"),
    )
    mock_refresh_repo = AsyncMock(spec=RefreshTokenRepository)
    service = UserService(mock_session, repo=mock_user_repo, refresh_repo=mock_refresh_repo)

    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_user_service] = lambda: service

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
    assert response.json()["error"] == "CONFLICT"
    mock_session.rollback.assert_awaited_once()


@pytest.mark.anyio
async def test_member_update_or_delete_other_user_returns_403() -> None:
    """Member attempting to view, update, or delete another user must receive 403 Forbidden."""
    member = _make_user(10, "member@example.com", role=UserRole.MEMBER)
    mock_session = AsyncMock(spec=AsyncSession)
    mock_user_repo = AsyncMock(spec=UserRepository)
    mock_user_repo.get_by_id.return_value = member
    mock_blacklist = AsyncMock(spec=TokenBlacklistService)
    mock_blacklist.is_blacklisted.return_value = False

    app.dependency_overrides[get_db] = lambda: mock_session
    app.dependency_overrides[get_user_repository] = lambda: mock_user_repo
    app.dependency_overrides[get_refresh_token_repository] = lambda: AsyncMock(
        spec=RefreshTokenRepository
    )
    app.dependency_overrides[get_token_blacklist] = lambda: mock_blacklist

    member_token = create_access_token(member.id, member.role)
    headers = {"Authorization": f"Bearer {member_token}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        get_resp = await ac.get("/api/v1/users/99", headers=headers)
        patch_resp = await ac.patch(
            "/api/v1/users/99",
            json={"full_name": "Hacked"},
            headers=headers,
        )
        delete_resp = await ac.delete("/api/v1/users/99", headers=headers)

    assert get_resp.status_code == 403
    assert patch_resp.status_code == 403
    assert delete_resp.status_code == 403


@pytest.mark.anyio
async def test_member_list_and_create_users_returns_403() -> None:
    """Member attempting admin list (GET /users) or create (POST /users) must receive 403."""
    member = _make_user(10, "member@example.com", role=UserRole.MEMBER)
    mock_session = AsyncMock(spec=AsyncSession)
    mock_user_repo = AsyncMock(spec=UserRepository)
    mock_user_repo.get_by_id.return_value = member
    mock_blacklist = AsyncMock(spec=TokenBlacklistService)
    mock_blacklist.is_blacklisted.return_value = False

    app.dependency_overrides[get_db] = lambda: mock_session
    app.dependency_overrides[get_user_repository] = lambda: mock_user_repo
    app.dependency_overrides[get_refresh_token_repository] = lambda: AsyncMock(
        spec=RefreshTokenRepository
    )
    app.dependency_overrides[get_token_blacklist] = lambda: mock_blacklist

    member_token = create_access_token(member.id, member.role)
    headers = {"Authorization": f"Bearer {member_token}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        list_resp = await ac.get("/api/v1/users", headers=headers)
        create_resp = await ac.post(
            "/api/v1/users",
            headers=headers,
            json={
                "email": "created_by_member@example.com",
                "full_name": "Unauthorized Create",
                "password": "ValidPassword123!",
            },
        )

    assert list_resp.status_code == 403
    assert create_resp.status_code == 403


@pytest.mark.anyio
async def test_admin_cannot_delete_self_returns_400() -> None:
    """An admin must not be allowed to delete their own account."""
    admin = _make_user(1, "admin@example.com", role=UserRole.ADMIN)
    mock_session = AsyncMock(spec=AsyncSession)
    mock_user_repo = AsyncMock(spec=UserRepository)
    service = UserService(mock_session, repo=mock_user_repo)

    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_user_service] = lambda: service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.delete("/api/v1/users/1")

    assert response.status_code == 400
    assert response.json()["error"] == "BAD_REQUEST"


@pytest.mark.anyio
async def test_cannot_demote_or_deactivate_last_active_admin() -> None:
    """Admin cannot demote or deactivate the sole remaining active admin."""
    admin = _make_user(1, "admin@example.com", role=UserRole.ADMIN)
    mock_session = AsyncMock(spec=AsyncSession)
    mock_user_repo = AsyncMock(spec=UserRepository)
    mock_user_repo.get_by_id.return_value = admin
    mock_user_repo.count_active_admins.return_value = 1
    service = UserService(mock_session, repo=mock_user_repo)

    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_user_service] = lambda: service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        demote_resp = await ac.patch("/api/v1/users/1", json={"role": "MEMBER"})
        deactivate_resp = await ac.patch("/api/v1/users/1", json={"is_active": False})

    assert demote_resp.status_code == 400
    assert deactivate_resp.status_code == 400


@pytest.mark.anyio
async def test_update_user_explicit_null_returns_422() -> None:
    """Sending explicit null for non-nullable fields on update must return 422."""
    member = _make_user(2, "member@example.com", role=UserRole.MEMBER)
    admin = _make_user(1, "admin@example.com", role=UserRole.ADMIN)
    app.dependency_overrides[get_current_user] = lambda: member

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        me_resp = await ac.patch("/api/v1/users/me", json={"full_name": None})

        app.dependency_overrides[get_current_user] = lambda: admin
        admin_role_resp = await ac.patch("/api/v1/users/2", json={"role": None})
        admin_active_resp = await ac.patch("/api/v1/users/2", json={"is_active": None})

    assert me_resp.status_code == 422
    assert me_resp.json()["error"] == "VALIDATION_ERROR"
    assert admin_role_resp.status_code == 422
    assert admin_active_resp.status_code == 422


@pytest.mark.anyio
async def test_create_user_service_conflict_propagates_409() -> None:
    """ConflictException raised by UserService returns uniform 409 error payload."""
    admin = _make_user(1, "admin@example.com", role=UserRole.ADMIN)
    mock_service = AsyncMock(spec=UserService)
    mock_service.create_user.side_effect = ConflictException(
        "Email 'dup@example.com' is already registered"
    )

    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_user_service] = lambda: mock_service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/api/v1/users",
            json={
                "email": "dup@example.com",
                "full_name": "Dup",
                "password": "valid_password_123",
            },
        )
    assert response.status_code == 409
    assert response.json()["error"] == "CONFLICT"
