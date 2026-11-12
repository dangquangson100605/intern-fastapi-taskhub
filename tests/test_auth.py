"""End-to-end authentication, token rotation, RBAC, and validation tests."""

import asyncio
import uuid
from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import patch

import httpx
import pytest
from jose import jwt
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.core.dependencies import (
    get_db,
    get_refresh_token_repository,
    get_token_blacklist,
    get_user_repository,
)
from app.core.exceptions import ServiceUnavailableException
from app.core.messages import ERROR_INACTIVE_USER
from app.core.redis import TokenBlacklistService
from app.core.security import DUMMY_PASSWORD_HASH, verify_password
from app.main import app
from app.models.enums import TokenType, UserRole
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.refresh_token import RefreshTokenRepository

settings = get_settings()


class FakeAsyncSession:
    """In-memory async session tracking commits and rollbacks."""

    def __init__(self) -> None:
        self.commit_count: int = 0
        self.rollback_count: int = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class InMemoryUserRepository:
    """Stateful in-memory UserRepository enforcing unique email constraints."""

    def __init__(self, session: FakeAsyncSession) -> None:
        self.session = session
        self._users: dict[int, User] = {}
        self._next_id: int = 1

    async def create(self, **kwargs: Any) -> User:
        email = str(kwargs["email"])
        if any(u.email == email for u in self._users.values()):
            raise IntegrityError(
                "INSERT INTO users",
                {},
                Exception(
                    f"1062 (23000): Duplicate entry '{email}' for key 'users.ix_users_email'"
                ),
            )
        user = User(
            id=self._next_id,
            email=email,
            full_name=str(kwargs["full_name"]),
            hashed_password=str(kwargs["hashed_password"]),
            role=kwargs.get("role", UserRole.MEMBER),
            is_active=bool(kwargs.get("is_active", True)),
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self._users[self._next_id] = user
        self._next_id += 1
        return user

    async def get_by_id(self, record_id: int) -> User | None:
        return self._users.get(record_id)

    async def get_by_email(self, email: str) -> User | None:
        for user in self._users.values():
            if user.email == email:
                return user
        return None

    async def count_active_admins(self) -> int:
        return sum(1 for u in self._users.values() if u.role == UserRole.ADMIN and u.is_active)

    async def update(self, record_id: int, **kwargs: Any) -> User | None:
        user = self._users.get(record_id)
        if user is None:
            return None
        new_email = kwargs.get("email")
        if new_email is not None and any(
            u.email == new_email and u.id != record_id for u in self._users.values()
        ):
            raise IntegrityError(
                "UPDATE users",
                {},
                Exception(
                    f"1062 (23000): Duplicate entry '{new_email}' for key 'users.ix_users_email'"
                ),
            )
        for field, value in kwargs.items():
            if hasattr(user, field):
                setattr(user, field, value)
        return user


class InMemoryRefreshTokenRepository:
    """Stateful in-memory RefreshTokenRepository supporting atomic rotation."""

    def __init__(self, session: FakeAsyncSession) -> None:
        self.session = session
        self._tokens: dict[str, RefreshToken] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._next_id: int = 1

    async def create_token(
        self,
        user_id: int,
        jti: str,
        expires_at: datetime,
    ) -> RefreshToken:
        record = RefreshToken(
            id=self._next_id,
            user_id=user_id,
            jti=jti,
            expires_at=expires_at.replace(tzinfo=None),
            revoked=False,
            revoked_at=None,
            replaced_by_jti=None,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self._tokens[jti] = record
        self._locks[jti] = asyncio.Lock()
        self._next_id += 1
        return record

    async def get_by_jti(self, jti: str, for_update: bool = False) -> RefreshToken | None:
        if for_update:
            lock = self._locks.setdefault(jti, asyncio.Lock())
            async with lock:
                await asyncio.sleep(0)
                return self._tokens.get(jti)
        await asyncio.sleep(0)
        return self._tokens.get(jti)

    async def atomic_revoke_by_jti(
        self,
        jti: str,
        replaced_by_jti: str | None = None,
    ) -> bool:
        lock = self._locks.setdefault(jti, asyncio.Lock())
        async with lock:
            await asyncio.sleep(0)
            record = self._tokens.get(jti)
            if record is None or record.revoked:
                return False
            record.revoked = True
            record.revoked_at = datetime.now(UTC).replace(tzinfo=None)
            record.replaced_by_jti = replaced_by_jti
            return True

    async def revoke_all_for_user(self, user_id: int) -> int:
        count = 0
        now_utc = datetime.now(UTC).replace(tzinfo=None)
        for record in self._tokens.values():
            if record.user_id == user_id and not record.revoked:
                record.revoked = True
                record.revoked_at = now_utc
                count += 1
        return count


class InMemoryBlacklistService(TokenBlacklistService):
    """In-memory Redis blacklist replacement for isolated auth tests."""

    def __init__(self) -> None:
        self._revoked_jtis: set[str] = set()

    async def blacklist_token(self, jti: str, exp_timestamp: int) -> None:
        _ = exp_timestamp
        self._revoked_jtis.add(jti)

    async def is_blacklisted(self, jti: str) -> bool:
        return jti in self._revoked_jtis


class AuthTestContext:
    """Container holding stateful in-memory auth dependencies for a test."""

    def __init__(self) -> None:
        self.session = FakeAsyncSession()
        self.user_repo = InMemoryUserRepository(self.session)
        self.refresh_repo = InMemoryRefreshTokenRepository(self.session)
        self.blacklist = InMemoryBlacklistService()


@pytest.fixture
def auth_ctx() -> Generator[AuthTestContext, None, None]:
    """Wire in-memory repositories and Redis blacklist into FastAPI overrides."""
    ctx = AuthTestContext()
    app.dependency_overrides[get_db] = lambda: ctx.session
    app.dependency_overrides[get_user_repository] = lambda: ctx.user_repo
    app.dependency_overrides[get_refresh_token_repository] = lambda: ctx.refresh_repo
    app.dependency_overrides[get_token_blacklist] = lambda: ctx.blacklist
    yield ctx
    app.dependency_overrides.clear()


async def _register_and_login(
    ac: httpx.AsyncClient,
    email: str = "alice@example.com",
    password: str = "StrongPass123!",
    full_name: str = "Alice Doe",
) -> dict[str, Any]:
    """Helper to register a user and return the login token payload."""
    reg = await ac.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": full_name, "password": password},
    )
    assert reg.status_code == 201
    login = await ac.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200
    data: dict[str, Any] = login.json()
    return data


@pytest.mark.anyio
async def test_register_ignores_client_role_and_rejects_duplicate_email(
    auth_ctx: AuthTestContext,
) -> None:
    """Registration always assigns MEMBER role and returns 409 on duplicate email."""
    _ = auth_ctx
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        first = await ac.post(
            "/api/v1/auth/register",
            json={
                "email": "bob@example.com",
                "full_name": "Bob Builder",
                "password": "StrongPassword123",
                "role": "ADMIN",
            },
        )
        second = await ac.post(
            "/api/v1/auth/register",
            json={
                "email": "bob@example.com",
                "full_name": "Bob Duplicate",
                "password": "StrongPassword123",
            },
        )

    assert first.status_code == 201
    assert first.json()["role"] == "MEMBER"
    assert second.status_code == 409
    assert second.json()["error"] == "CONFLICT"


@pytest.mark.anyio
async def test_multibyte_password_over_72_bytes_returns_422_on_auth_endpoints(
    auth_ctx: AuthTestContext,
) -> None:
    """Passwords > 72 UTF-8 bytes (< 72 chars) must fail with 422 on register, login, and password change."""
    multibyte_75_bytes = "ắ" * 25
    assert len(multibyte_75_bytes) == 25
    assert len(multibyte_75_bytes.encode("utf-8")) == 75

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        tokens = await _register_and_login(ac)

        reg_resp = await ac.post(
            "/api/v1/auth/register",
            json={
                "email": "utf8@example.com",
                "full_name": "UTF8 User",
                "password": multibyte_75_bytes,
            },
        )
        login_resp = await ac.post(
            "/api/v1/auth/login",
            json={"email": "alice@example.com", "password": multibyte_75_bytes},
        )
        pwd_resp = await ac.patch(
            "/api/v1/users/me/password",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            json={
                "current_password": "StrongPass123!",
                "new_password": multibyte_75_bytes,
            },
        )

    assert auth_ctx.user_repo is not None
    assert reg_resp.status_code == 422
    assert login_resp.status_code == 422
    assert pwd_resp.status_code == 422


@pytest.mark.anyio
async def test_refresh_token_cannot_access_protected_api_returns_401(
    auth_ctx: AuthTestContext,
) -> None:
    """Using a refresh token in Authorization Bearer header must return 401 with WWW-Authenticate."""
    _ = auth_ctx
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        tokens = await _register_and_login(ac)
        resp = await ac.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
        )

    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


@pytest.mark.anyio
async def test_valid_jwt_with_invalid_sub_returns_401(
    auth_ctx: AuthTestContext,
) -> None:
    """A validly signed token with non-numeric or missing sub must return 401, never 500."""
    _ = auth_ctx
    now = datetime.now(UTC)
    garbage_sub_token = jwt.encode(
        {
            "sub": "not-an-integer",
            "type": TokenType.ACCESS.value,
            "jti": "test-jti-1",
            "iat": int(now.timestamp()),
            "exp": now + timedelta(minutes=15),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    bool_sub_token = jwt.encode(
        {
            "sub": True,
            "type": TokenType.ACCESS.value,
            "jti": "test-jti-2",
            "iat": int(now.timestamp()),
            "exp": now + timedelta(minutes=15),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        r1 = await ac.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {garbage_sub_token}"},
        )
        r2 = await ac.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {bool_sub_token}"},
        )

    assert r1.status_code == 401
    assert r1.headers.get("www-authenticate") == "Bearer"
    assert r2.status_code == 401
    assert r2.headers.get("www-authenticate") == "Bearer"


@pytest.mark.anyio
async def test_reuse_of_rotated_refresh_token_returns_401_and_revokes_all_sessions(
    auth_ctx: AuthTestContext,
) -> None:
    """Reusing an already rotated refresh token returns 401 and revokes every active session."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        initial = await _register_and_login(ac)
        old_refresh = initial["refresh_token"]

        rotated = await ac.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        assert rotated.status_code == 200
        new_refresh = rotated.json()["refresh_token"]
        assert new_refresh != old_refresh

        reused = await ac.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        assert reused.status_code == 401
        assert reused.headers.get("www-authenticate") == "Bearer"

        after_compromise = await ac.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": new_refresh},
        )
        assert after_compromise.status_code == 401

    assert auth_ctx.session.commit_count >= 1


@pytest.mark.anyio
async def test_login_with_old_password_after_change_returns_401_and_revokes_refresh(
    auth_ctx: AuthTestContext,
) -> None:
    """Changing password invalidates old password logins and revokes prior refresh tokens."""
    _ = auth_ctx
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        tokens = await _register_and_login(ac, password="OldPassword123!")

        change_resp = await ac.patch(
            "/api/v1/users/me/password",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            json={
                "current_password": "OldPassword123!",
                "new_password": "NewPassword456!",
            },
        )
        assert change_resp.status_code == 200

        old_login = await ac.post(
            "/api/v1/auth/login",
            json={"email": "alice@example.com", "password": "OldPassword123!"},
        )
        old_refresh = await ac.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        new_login = await ac.post(
            "/api/v1/auth/login",
            json={"email": "alice@example.com", "password": "NewPassword456!"},
        )

    assert old_login.status_code == 401
    assert old_login.headers.get("www-authenticate") == "Bearer"
    assert old_refresh.status_code == 401
    assert new_login.status_code == 200


@pytest.mark.anyio
async def test_logout_blacklists_access_token_and_revokes_refresh_token(
    auth_ctx: AuthTestContext,
) -> None:
    """Logged-out access token and refresh token cannot be used afterward."""
    _ = auth_ctx
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        tokens = await _register_and_login(ac)
        auth_headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        logout_resp = await ac.post(
            "/api/v1/auth/logout",
            headers=auth_headers,
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert logout_resp.status_code == 200

        me_after_logout = await ac.get("/api/v1/users/me", headers=auth_headers)
        refresh_after_logout = await ac.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )

    assert me_after_logout.status_code == 401
    assert me_after_logout.headers.get("www-authenticate") == "Bearer"
    assert refresh_after_logout.status_code == 401


@pytest.mark.anyio
async def test_inactive_user_reports_inactive_message_on_login_and_api(
    auth_ctx: AuthTestContext,
) -> None:
    """Deactivated user must receive specific 'Inactive user' error message, not 'Invalid token'."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        tokens = await _register_and_login(ac)
        user = await auth_ctx.user_repo.get_by_email("alice@example.com")
        assert user is not None
        user.is_active = False

        api_resp = await ac.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        login_resp = await ac.post(
            "/api/v1/auth/login",
            json={"email": "alice@example.com", "password": "StrongPass123!"},
        )

    assert api_resp.status_code == 401
    assert api_resp.json()["message"] == ERROR_INACTIVE_USER
    assert api_resp.headers.get("www-authenticate") == "Bearer"
    assert login_resp.status_code == 401
    assert login_resp.json()["message"] == ERROR_INACTIVE_USER


def test_settings_rejects_empty_or_short_jwt_secret_key() -> None:
    """Settings validation must reject empty, short, or placeholder JWT_SECRET_KEY values."""
    with pytest.raises(ValidationError):
        Settings(DB_PASSWORD="test", JWT_SECRET_KEY="")

    with pytest.raises(ValidationError):
        Settings(DB_PASSWORD="test", JWT_SECRET_KEY="short-key")

    with pytest.raises(ValidationError):
        Settings(DB_PASSWORD="test", JWT_SECRET_KEY="CHANGE_ME")

    with pytest.raises(ValidationError):
        Settings(
            DB_PASSWORD="test",
            JWT_SECRET_KEY="CHANGE_ME_123456789012345678901234567890",
        )

    with pytest.raises(ValidationError):
        Settings(
            DB_PASSWORD="test",
            JWT_SECRET_KEY="your-super-secret-key-change-in-production",
        )


@pytest.mark.anyio
async def test_concurrent_refresh_requests_only_one_succeeds(
    auth_ctx: AuthTestContext,
) -> None:
    """Two simultaneous refresh requests with the same token allow only one to succeed."""
    _ = auth_ctx
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        tokens = await _register_and_login(ac)
        r1, r2 = await asyncio.gather(
            ac.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}),
            ac.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}),
        )

    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 401]


@pytest.mark.anyio
async def test_concurrent_refresh_rotation_is_atomic_against_real_mysql() -> None:
    """Concurrent refresh calls against MySQL must serialize via FOR UPDATE and atomic UPDATE."""
    engine = create_async_engine(
        settings.DATABASE_URL,
        connect_args={"connect_timeout": 2},
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    try:
        async with session_factory() as probe_session:
            await probe_session.execute(text("SELECT 1"))
            await probe_session.execute(text("SELECT password_changed_at FROM users LIMIT 1"))
            await probe_session.execute(text("SELECT jti, revoked FROM refresh_tokens LIMIT 1"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"MySQL unavailable or schema unmigrated for concurrency test: {exc}")

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    blacklist = InMemoryBlacklistService()
    unique_email = f"concurrent-{uuid.uuid4().hex}@example.com"
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_token_blacklist] = lambda: blacklist

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as ac:
            tokens = await _register_and_login(ac, email=unique_email)
            r1, r2 = await asyncio.gather(
                ac.post(
                    "/api/v1/auth/refresh",
                    json={"refresh_token": tokens["refresh_token"]},
                ),
                ac.post(
                    "/api/v1/auth/refresh",
                    json={"refresh_token": tokens["refresh_token"]},
                ),
            )
        statuses = sorted([r1.status_code, r2.status_code])
        assert statuses == [200, 401]
    finally:
        app.dependency_overrides.clear()
        async with session_factory() as cleanup_session:
            await cleanup_session.execute(delete(User).where(User.email == unique_email))
            await cleanup_session.commit()
        await engine.dispose()


@pytest.mark.anyio
async def test_refresh_repository_sql_uses_for_update_and_atomic_where_clause() -> None:
    """RefreshTokenRepository emits SELECT ... FOR UPDATE and atomic WHERE revoked IS false."""
    compiled_sql: list[str] = []

    class FakeResult:
        rowcount = 1

        def scalar_one_or_none(self) -> None:
            return None

    class RecordingSession:
        async def execute(self, stmt: Any) -> FakeResult:
            compiled = stmt.compile(dialect=mysql.dialect())
            compiled_sql.append(str(compiled))
            return FakeResult()

    repo = RefreshTokenRepository(cast(AsyncSession, RecordingSession()))
    await repo.get_by_jti("test-jti", for_update=True)
    revoked = await repo.atomic_revoke_by_jti("test-jti", replaced_by_jti="next-jti")

    assert revoked is True
    assert len(compiled_sql) == 2
    assert "FOR UPDATE" in compiled_sql[0].upper()
    assert "UPDATE REFRESH_TOKENS" in compiled_sql[1].upper()
    assert "REVOKED IS FALSE" in compiled_sql[1].upper()


@pytest.mark.anyio
async def test_login_runs_bcrypt_verify_for_unknown_email(
    auth_ctx: AuthTestContext,
) -> None:
    """Login still executes bcrypt verification with dummy hash when email does not exist."""
    _ = auth_ctx
    with patch(
        "app.services.auth.verify_password",
        wraps=verify_password,
    ) as mock_verify:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/api/v1/auth/login",
                json={"email": "nobody@example.com", "password": "SomePassword123!"},
            )

    assert resp.status_code == 401
    mock_verify.assert_called_once_with("SomePassword123!", DUMMY_PASSWORD_HASH)


@pytest.mark.anyio
async def test_logout_invalid_or_foreign_refresh_does_not_blacklist_access_token(
    auth_ctx: AuthTestContext,
) -> None:
    """Invalid, already-revoked, or foreign refresh token must not blacklist access token."""
    _ = auth_ctx
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        alice_tokens = await _register_and_login(ac, email="alice@example.com")
        bob_tokens = await _register_and_login(ac, email="bob@example.com")
        headers = {"Authorization": f"Bearer {alice_tokens['access_token']}"}

        foreign_resp = await ac.post(
            "/api/v1/auth/logout",
            headers=headers,
            json={"refresh_token": bob_tokens["refresh_token"]},
        )
        assert foreign_resp.status_code == 403

        me_after_foreign = await ac.get("/api/v1/users/me", headers=headers)
        assert me_after_foreign.status_code == 200

        refresh_resp = await ac.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": alice_tokens["refresh_token"]},
        )
        assert refresh_resp.status_code == 200

        revoked_logout = await ac.post(
            "/api/v1/auth/logout",
            headers=headers,
            json={"refresh_token": alice_tokens["refresh_token"]},
        )
        assert revoked_logout.status_code == 401

        me_after_revoked = await ac.get("/api/v1/users/me", headers=headers)
        assert me_after_revoked.status_code == 200


@pytest.mark.anyio
async def test_change_password_invalidates_all_existing_access_tokens(
    auth_ctx: AuthTestContext,
) -> None:
    """Changing password invalidates every access token issued before password_changed_at."""
    _ = auth_ctx
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        first_login = await _register_and_login(ac)
        second_login_resp = await ac.post(
            "/api/v1/auth/login",
            json={"email": "alice@example.com", "password": "StrongPass123!"},
        )
        assert second_login_resp.status_code == 200
        second_login = second_login_resp.json()

        await asyncio.sleep(0.01)
        change_resp = await ac.patch(
            "/api/v1/users/me/password",
            headers={"Authorization": f"Bearer {first_login['access_token']}"},
            json={
                "current_password": "StrongPass123!",
                "new_password": "BrandNewPassword123!",
            },
        )
        assert change_resp.status_code == 200

        me_first = await ac.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {first_login['access_token']}"},
        )
        me_second = await ac.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {second_login['access_token']}"},
        )
        assert me_first.status_code == 401
        assert me_second.status_code == 401

        new_login = await ac.post(
            "/api/v1/auth/login",
            json={"email": "alice@example.com", "password": "BrandNewPassword123!"},
        )
        assert new_login.status_code == 200
        me_new = await ac.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {new_login.json()['access_token']}"},
        )
        assert me_new.status_code == 200


@pytest.mark.anyio
async def test_password_preserves_leading_and_trailing_spaces(
    auth_ctx: AuthTestContext,
) -> None:
    """Password fields must not strip leading or trailing whitespace."""
    _ = auth_ctx
    spaced_password = "  SpacePass123!  "
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        reg = await ac.post(
            "/api/v1/auth/register",
            json={
                "email": "spaced@example.com",
                "full_name": "Spaced Password User",
                "password": spaced_password,
            },
        )
        assert reg.status_code == 201

        login_trimmed = await ac.post(
            "/api/v1/auth/login",
            json={"email": "spaced@example.com", "password": spaced_password.strip()},
        )
        login_exact = await ac.post(
            "/api/v1/auth/login",
            json={"email": "spaced@example.com", "password": spaced_password},
        )

    assert login_trimmed.status_code == 401
    assert login_exact.status_code == 200


@pytest.mark.anyio
async def test_redis_failure_returns_503_service_unavailable(
    auth_ctx: AuthTestContext,
) -> None:
    """Redis connectivity or timeout errors translate to 503 Service Unavailable."""

    class FailingRedis:
        async def setex(self, name: str, time: int, value: str) -> None:
            _ = (name, time, value)
            raise RedisError("Redis timeout")

        async def exists(self, name: str) -> int:
            _ = name
            raise RedisError("Redis connection refused")

    failing_blacklist = TokenBlacklistService(cast(Redis, FailingRedis()))

    with pytest.raises(ServiceUnavailableException):
        await failing_blacklist.blacklist_token("jti-1", int(datetime.now(UTC).timestamp()) + 60)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        tokens = await _register_and_login(ac)
        app.dependency_overrides[get_token_blacklist] = lambda: failing_blacklist
        me_resp = await ac.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        logout_resp = await ac.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )

    assert me_resp.status_code == 503
    assert me_resp.json()["error"] == "SERVICE_UNAVAILABLE"
    assert logout_resp.status_code == 503
    assert logout_resp.json()["error"] == "SERVICE_UNAVAILABLE"
