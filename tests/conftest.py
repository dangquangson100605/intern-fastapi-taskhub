"""Pytest configuration and shared fixtures."""

import fnmatch
import math
from collections.abc import AsyncGenerator, Sequence
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from redis.exceptions import RedisError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.enums import UserRole, WorkspaceRole
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.repositories.base import PaginationResult
from app.repositories.user import UserRepository
from app.repositories.workspace import WorkspaceRepository
from app.repositories.workspace_member import WorkspaceMemberRepository


@pytest.fixture
def anyio_backend() -> str:
    """Only test on asyncio backend."""
    return "asyncio"


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide an asynchronous HTTP client bound to the FastAPI test application."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


class FakeAsyncSession:
    """In-memory async session recording commit and rollback actions."""

    def __init__(self) -> None:
        self.commit_count: int = 0
        self.rollback_count: int = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def refresh(self, instance: Any, attribute_names: Sequence[str] | None = None) -> None:
        _ = (instance, attribute_names)


class FakeRedis:
    """In-memory Redis fake supporting get, setex, incr, delete, scan_iter, and unlink."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.simulate_error: bool = False

    async def get(self, key: str) -> str | None:
        if self.simulate_error:
            raise RedisError("Simulated Redis get failure")
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        _ = ttl
        if self.simulate_error:
            raise RedisError("Simulated Redis set failure")
        self.store[key] = value
        return True

    async def incr(self, key: str) -> int:
        if self.simulate_error:
            raise RedisError("Simulated Redis incr failure")
        current = int(self.store.get(key, "1"))
        new_val = current + 1
        self.store[key] = str(new_val)
        return new_val

    async def delete(self, key: str) -> int:
        if self.simulate_error:
            raise RedisError("Simulated Redis delete failure")
        if key in self.store:
            del self.store[key]
            return 1
        return 0

    async def scan_iter(self, match: str = "*", count: int = 100) -> AsyncGenerator[str, None]:
        _ = count
        if self.simulate_error:
            raise RedisError("Simulated Redis scan failure")
        for k in list(self.store.keys()):
            if fnmatch.fnmatch(k, match):
                yield k

    async def unlink(self, *keys: str) -> int:
        if self.simulate_error:
            raise RedisError("Simulated Redis unlink failure")
        deleted = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                deleted += 1
        return deleted


class InMemoryUserRepository(UserRepository):
    """In-memory user repository backing test actors."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._users: dict[int, User] = {}

    def add_test_user(
        self,
        user_id: int,
        email: str,
        role: UserRole = UserRole.MEMBER,
        is_active: bool = True,
    ) -> User:
        user = User(
            id=user_id,
            email=email,
            full_name=f"User {user_id}",
            hashed_password="hash",
            role=role,
            is_active=is_active,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self._users[user_id] = user
        return user

    async def get_by_id(self, record_id: int) -> User | None:
        return self._users.get(record_id)


class InMemoryWorkspaceMemberRepository(WorkspaceMemberRepository):
    """In-memory workspace member repository."""

    def __init__(self, session: AsyncSession, user_repo: InMemoryUserRepository) -> None:
        super().__init__(session)
        self.user_repo = user_repo
        self._members: dict[tuple[int, int], WorkspaceMember] = {}
        self._next_id: int = 1

    async def get_member(self, workspace_id: int, user_id: int) -> WorkspaceMember | None:
        member = self._members.get((workspace_id, user_id))
        if member is not None:
            member.user = self.user_repo._users.get(user_id)  # type: ignore[assignment]
        return member

    async def list_members(
        self, workspace_id: int, page: int = 1, limit: int = 20
    ) -> PaginationResult[WorkspaceMember]:
        matched = [m for m in self._members.values() if m.workspace_id == workspace_id]
        for m in matched:
            m.user = self.user_repo._users.get(m.user_id)  # type: ignore[assignment]
        total = len(matched)
        offset = (page - 1) * limit
        items = matched[offset : offset + limit]
        return PaginationResult(
            items=items,
            total=total,
            page=page,
            limit=limit,
            total_pages=math.ceil(total / limit) if limit > 0 else 0,
        )

    async def add_member(
        self,
        workspace_id: int,
        user_id: int,
        role: WorkspaceRole = WorkspaceRole.VIEWER,
    ) -> WorkspaceMember:
        if (workspace_id, user_id) in self._members:
            raise IntegrityError(
                "INSERT INTO workspace_members",
                {},
                Exception("Duplicate entry for key 'uq_workspace_user'"),
            )
        member = WorkspaceMember(
            id=self._next_id,
            workspace_id=workspace_id,
            user_id=user_id,
            role=role,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self._next_id += 1
        member.user = self.user_repo._users.get(user_id)  # type: ignore[assignment]
        self._members[(workspace_id, user_id)] = member
        return member

    async def update_role(
        self, workspace_id: int, user_id: int, role: WorkspaceRole
    ) -> WorkspaceMember | None:
        member = await self.get_member(workspace_id, user_id)
        if member is None:
            return None
        member.role = role
        return member

    async def remove_member(self, workspace_id: int, user_id: int) -> bool:
        if (workspace_id, user_id) in self._members:
            del self._members[(workspace_id, user_id)]
            return True
        return False

    async def get_roles_by_workspace_ids(
        self, workspace_ids: Sequence[int], user_id: int
    ) -> dict[int, WorkspaceRole]:
        res: dict[int, WorkspaceRole] = {}
        for ws_id in workspace_ids:
            if (ws_id, user_id) in self._members:
                res[ws_id] = self._members[(ws_id, user_id)].role
        return res


class InMemoryWorkspaceRepository(WorkspaceRepository):
    """In-memory workspace repository."""

    def __init__(
        self,
        session: AsyncSession,
        member_repo: InMemoryWorkspaceMemberRepository,
    ) -> None:
        super().__init__(session)
        self.member_repo = member_repo
        self._workspaces: dict[int, Workspace] = {}
        self._next_id: int = 1

    async def create(self, **kwargs: Any) -> Workspace:
        ws = Workspace(
            id=self._next_id,
            name=str(kwargs["name"]),
            owner_id=int(kwargs["owner_id"]),
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self._workspaces[self._next_id] = ws
        self._next_id += 1
        return ws

    async def get_by_id(self, record_id: int) -> Workspace | None:
        return self._workspaces.get(record_id)

    async def list_for_user(
        self, user_id: int, page: int = 1, limit: int = 20
    ) -> PaginationResult[Workspace]:
        accessible = [
            ws
            for ws in self._workspaces.values()
            if ws.owner_id == user_id or (ws.id, user_id) in self.member_repo._members
        ]
        total = len(accessible)
        offset = (page - 1) * limit
        items = accessible[offset : offset + limit]
        return PaginationResult(
            items=items,
            total=total,
            page=page,
            limit=limit,
            total_pages=math.ceil(total / limit) if limit > 0 else 0,
        )
