"""Unit, RBAC, and ownership isolation tests for Workspace endpoints."""

import math
import uuid
from collections.abc import Generator, Sequence
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.dependencies import (
    get_current_user,
    get_db,
    get_workspace_member_repository,
    get_workspace_repository,
    get_workspace_service,
)
from app.core.messages import (
    ERROR_CANNOT_DEMOTE_OR_REMOVE_WORKSPACE_OWNER,
    ERROR_PERMISSION_DENIED,
    ERROR_WORKSPACE_MEMBER_ALREADY_EXISTS,
    ERROR_WORKSPACE_NOT_FOUND,
)
from app.main import app
from app.models.enums import UserRole, WorkspaceRole
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.repositories.base import PaginationResult
from app.repositories.user import UserRepository
from app.repositories.workspace import WorkspaceRepository
from app.repositories.workspace_member import WorkspaceMemberRepository
from app.services.workspace import WorkspaceService


class FakeAsyncSession:
    """In-memory async session recording commit and rollback invocations."""

    def __init__(self) -> None:
        self.commit_count: int = 0
        self.rollback_count: int = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def refresh(self, instance: Any) -> None:
        _ = instance


class InMemoryUserRepository(UserRepository):
    """In-memory user repository backing test users."""

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

    async def list_all_paginated(
        self, page: int = 1, limit: int = 20
    ) -> PaginationResult[Workspace]:
        all_ws = list(self._workspaces.values())
        total = len(all_ws)
        offset = (page - 1) * limit
        items = all_ws[offset : offset + limit]
        return PaginationResult(
            items=items,
            total=total,
            page=page,
            limit=limit,
            total_pages=math.ceil(total / limit) if limit > 0 else 0,
        )

    async def delete(self, record_id: int) -> bool:
        if record_id in self._workspaces:
            del self._workspaces[record_id]
            keys_to_del = [k for k in self.member_repo._members if k[0] == record_id]
            for k in keys_to_del:
                del self.member_repo._members[k]
            return True
        return False


class WorkspaceTestContext:
    """Holds test repositories, session, and users for workspace testing."""

    def __init__(self) -> None:
        self.session = cast(AsyncSession, FakeAsyncSession())
        self.user_repo = InMemoryUserRepository(self.session)
        self.member_repo = InMemoryWorkspaceMemberRepository(self.session, self.user_repo)
        self.workspace_repo = InMemoryWorkspaceRepository(self.session, self.member_repo)
        self.service = WorkspaceService(
            session=self.session,
            workspace_repo=self.workspace_repo,
            member_repo=self.member_repo,
            user_repo=self.user_repo,
        )

        self.user_a = self.user_repo.add_test_user(1, "alice@example.com")
        self.user_b = self.user_repo.add_test_user(2, "bob@example.com")
        self.user_c = self.user_repo.add_test_user(3, "charlie@example.com")
        self.admin = self.user_repo.add_test_user(4, "admin@example.com", role=UserRole.ADMIN)
        self.inactive_user = self.user_repo.add_test_user(
            5, "inactive@example.com", is_active=False
        )


@pytest.fixture
def ws_ctx() -> Generator[WorkspaceTestContext, None, None]:
    """Provide isolated in-memory workspace test context with dependency overrides."""
    ctx = WorkspaceTestContext()
    app.dependency_overrides[get_db] = lambda: ctx.session
    app.dependency_overrides[get_workspace_repository] = lambda: ctx.workspace_repo
    app.dependency_overrides[get_workspace_member_repository] = lambda: ctx.member_repo
    app.dependency_overrides[get_workspace_service] = lambda: ctx.service
    yield ctx
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_create_workspace_success(ws_ctx: WorkspaceTestContext) -> None:
    """Creating a workspace succeeds and automatically registers creator as OWNER."""
    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_a
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post("/api/v1/workspaces", json={"name": "Alice Workspace"})

    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Alice Workspace"
    assert data["owner_id"] == ws_ctx.user_a.id
    assert data["role"] == "OWNER"

    member = await ws_ctx.member_repo.get_member(data["id"], ws_ctx.user_a.id)
    assert member is not None
    assert member.role == WorkspaceRole.OWNER


@pytest.mark.anyio
async def test_create_workspace_name_validation(
    ws_ctx: WorkspaceTestContext,
) -> None:
    """Empty or oversized workspace names must be rejected with 422."""
    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_a
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        empty_resp = await ac.post("/api/v1/workspaces", json={"name": ""})
        too_long_resp = await ac.post("/api/v1/workspaces", json={"name": "a" * 256})

    assert empty_resp.status_code == 422
    assert too_long_resp.status_code == 422


@pytest.mark.anyio
async def test_list_and_get_workspace_ownership_isolation(
    ws_ctx: WorkspaceTestContext,
) -> None:
    """User B cannot view or list workspaces owned by User A without membership."""
    ws_a = await ws_ctx.service.create_workspace(
        ws_ctx.user_a,
        type("WorkspaceCreate", (), {"name": "Workspace A"})(),  # type: ignore[arg-type]
    )
    ws_b = await ws_ctx.service.create_workspace(
        ws_ctx.user_b,
        type("WorkspaceCreate", (), {"name": "Workspace B"})(),  # type: ignore[arg-type]
    )

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_b
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        list_resp = await ac.get("/api/v1/workspaces")
        assert list_resp.status_code == 200
        items = list_resp.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == ws_b.id

        forbidden_get = await ac.get(f"/api/v1/workspaces/{ws_a.id}")
        assert forbidden_get.status_code == 403
        assert forbidden_get.json()["message"] == ERROR_PERMISSION_DENIED

        allowed_get = await ac.get(f"/api/v1/workspaces/{ws_b.id}")
        assert allowed_get.status_code == 200
        assert allowed_get.json()["name"] == "Workspace B"

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.admin
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        admin_list = await ac.get("/api/v1/workspaces")
        assert admin_list.status_code == 200
        assert len(admin_list.json()["items"]) == 2

        admin_get_a = await ac.get(f"/api/v1/workspaces/{ws_a.id}")
        assert admin_get_a.status_code == 200


@pytest.mark.anyio
async def test_get_workspace_not_found(ws_ctx: WorkspaceTestContext) -> None:
    """Non-existent workspace ID returns 404 Not Found."""
    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_a
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/api/v1/workspaces/9999")
    assert resp.status_code == 404
    assert resp.json()["message"] == ERROR_WORKSPACE_NOT_FOUND


@pytest.mark.anyio
async def test_update_workspace_permissions(
    ws_ctx: WorkspaceTestContext,
) -> None:
    """Only OWNER or system ADMIN can update workspace; others receive 403."""
    ws = await ws_ctx.service.create_workspace(
        ws_ctx.user_a,
        type("WorkspaceCreate", (), {"name": "Original"})(),  # type: ignore[arg-type]
    )

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_b
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        unauthorized_update = await ac.patch(
            f"/api/v1/workspaces/{ws.id}", json={"name": "Hacked Name"}
        )
    assert unauthorized_update.status_code == 403

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_a
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        null_update = await ac.patch(f"/api/v1/workspaces/{ws.id}", json={"name": None})
        assert null_update.status_code == 422

        owner_update = await ac.patch(
            f"/api/v1/workspaces/{ws.id}", json={"name": "Updated by Owner"}
        )
        assert owner_update.status_code == 200
        assert owner_update.json()["name"] == "Updated by Owner"

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.admin
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        admin_update = await ac.patch(
            f"/api/v1/workspaces/{ws.id}", json={"name": "Updated by Admin"}
        )
        assert admin_update.status_code == 200
        assert admin_update.json()["name"] == "Updated by Admin"


@pytest.mark.anyio
async def test_delete_workspace_permissions(
    ws_ctx: WorkspaceTestContext,
) -> None:
    """Only OWNER or system ADMIN can delete workspace; others receive 403."""
    ws_1 = await ws_ctx.service.create_workspace(
        ws_ctx.user_a,
        type("WorkspaceCreate", (), {"name": "Workspace 1"})(),  # type: ignore[arg-type]
    )
    ws_2 = await ws_ctx.service.create_workspace(
        ws_ctx.user_a,
        type("WorkspaceCreate", (), {"name": "Workspace 2"})(),  # type: ignore[arg-type]
    )

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_b
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        forbidden_del = await ac.delete(f"/api/v1/workspaces/{ws_1.id}")
    assert forbidden_del.status_code == 403

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.admin
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        admin_del = await ac.delete(f"/api/v1/workspaces/{ws_1.id}")
    assert admin_del.status_code == 200

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_a
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        owner_del = await ac.delete(f"/api/v1/workspaces/{ws_2.id}")
    assert owner_del.status_code == 200


@pytest.mark.anyio
async def test_add_workspace_member_flow_and_guards(
    ws_ctx: WorkspaceTestContext,
) -> None:
    """Validate adding members, duplicate checks, inactive users, and owner restrictions."""
    ws = await ws_ctx.service.create_workspace(
        ws_ctx.user_a,
        type("WorkspaceCreate", (), {"name": "Team Space"})(),  # type: ignore[arg-type]
    )

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_b
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        non_owner_add = await ac.post(
            f"/api/v1/workspaces/{ws.id}/members",
            json={"user_id": ws_ctx.user_c.id, "role": "EDITOR"},
        )
    assert non_owner_add.status_code == 403

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_a
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        not_found_user = await ac.post(
            f"/api/v1/workspaces/{ws.id}/members",
            json={"user_id": 9999, "role": "EDITOR"},
        )
        assert not_found_user.status_code == 404

        inactive_user_resp = await ac.post(
            f"/api/v1/workspaces/{ws.id}/members",
            json={"user_id": ws_ctx.inactive_user.id, "role": "EDITOR"},
        )
        assert inactive_user_resp.status_code == 400

        owner_role_attempt = await ac.post(
            f"/api/v1/workspaces/{ws.id}/members",
            json={"user_id": ws_ctx.user_b.id, "role": "OWNER"},
        )
        assert owner_role_attempt.status_code == 422

        successful_add = await ac.post(
            f"/api/v1/workspaces/{ws.id}/members",
            json={"user_id": ws_ctx.user_b.id, "role": "EDITOR"},
        )
        assert successful_add.status_code == 201
        data = successful_add.json()
        assert data["user_id"] == ws_ctx.user_b.id
        assert data["role"] == "EDITOR"
        assert data["user"]["email"] == ws_ctx.user_b.email

        duplicate_add = await ac.post(
            f"/api/v1/workspaces/{ws.id}/members",
            json={"user_id": ws_ctx.user_b.id, "role": "VIEWER"},
        )
        assert duplicate_add.status_code == 409
        assert duplicate_add.json()["message"] == ERROR_WORKSPACE_MEMBER_ALREADY_EXISTS


@pytest.mark.anyio
async def test_list_workspace_members(ws_ctx: WorkspaceTestContext) -> None:
    """Members and Admins can list workspace members; outsiders receive 403."""
    ws = await ws_ctx.service.create_workspace(
        ws_ctx.user_a,
        type("WorkspaceCreate", (), {"name": "Team Space"})(),  # type: ignore[arg-type]
    )
    await ws_ctx.member_repo.add_member(ws.id, ws_ctx.user_b.id, role=WorkspaceRole.EDITOR)

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_c
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        forbidden_list = await ac.get(f"/api/v1/workspaces/{ws.id}/members")
    assert forbidden_list.status_code == 403

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_b
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        member_list = await ac.get(f"/api/v1/workspaces/{ws.id}/members")
    assert member_list.status_code == 200
    assert member_list.json()["total"] == 2


@pytest.mark.anyio
async def test_update_member_role(ws_ctx: WorkspaceTestContext) -> None:
    """Role updates require OWNER or ADMIN and protect the owner from being demoted."""
    ws = await ws_ctx.service.create_workspace(
        ws_ctx.user_a,
        type("WorkspaceCreate", (), {"name": "Team Space"})(),  # type: ignore[arg-type]
    )
    await ws_ctx.member_repo.add_member(ws.id, ws_ctx.user_b.id, role=WorkspaceRole.EDITOR)

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_b
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        unauthorized_patch = await ac.patch(
            f"/api/v1/workspaces/{ws.id}/members/{ws_ctx.user_b.id}",
            json={"role": "VIEWER"},
        )
    assert unauthorized_patch.status_code == 403

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_a
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        demote_owner_attempt = await ac.patch(
            f"/api/v1/workspaces/{ws.id}/members/{ws_ctx.user_a.id}",
            json={"role": "VIEWER"},
        )
        assert demote_owner_attempt.status_code == 400
        assert (
            demote_owner_attempt.json()["message"] == ERROR_CANNOT_DEMOTE_OR_REMOVE_WORKSPACE_OWNER
        )

        assign_owner_attempt = await ac.patch(
            f"/api/v1/workspaces/{ws.id}/members/{ws_ctx.user_b.id}",
            json={"role": "OWNER"},
        )
        assert assign_owner_attempt.status_code == 422

        valid_update = await ac.patch(
            f"/api/v1/workspaces/{ws.id}/members/{ws_ctx.user_b.id}",
            json={"role": "VIEWER"},
        )
        assert valid_update.status_code == 200
        assert valid_update.json()["role"] == "VIEWER"


@pytest.mark.anyio
async def test_remove_member_flow(ws_ctx: WorkspaceTestContext) -> None:
    """Test member removal: owner removing members, member leaving, and owner protection."""
    ws = await ws_ctx.service.create_workspace(
        ws_ctx.user_a,
        type("WorkspaceCreate", (), {"name": "Team Space"})(),  # type: ignore[arg-type]
    )
    await ws_ctx.member_repo.add_member(ws.id, ws_ctx.user_b.id, role=WorkspaceRole.EDITOR)
    await ws_ctx.member_repo.add_member(ws.id, ws_ctx.user_c.id, role=WorkspaceRole.VIEWER)

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_a
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        remove_owner_attempt = await ac.delete(
            f"/api/v1/workspaces/{ws.id}/members/{ws_ctx.user_a.id}"
        )
    assert remove_owner_attempt.status_code == 400
    assert remove_owner_attempt.json()["message"] == ERROR_CANNOT_DEMOTE_OR_REMOVE_WORKSPACE_OWNER

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_c
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        unauthorized_del = await ac.delete(f"/api/v1/workspaces/{ws.id}/members/{ws_ctx.user_b.id}")
    assert unauthorized_del.status_code == 403

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_c
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        self_leave = await ac.delete(f"/api/v1/workspaces/{ws.id}/members/{ws_ctx.user_c.id}")
    assert self_leave.status_code == 200

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_a
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        owner_removes_b = await ac.delete(f"/api/v1/workspaces/{ws.id}/members/{ws_ctx.user_b.id}")
    assert owner_removes_b.status_code == 200

    remaining = await ws_ctx.member_repo.list_members(ws.id)
    assert remaining.total == 1
    assert remaining.items[0].user_id == ws_ctx.user_a.id


@pytest.mark.anyio
async def test_remove_member_outsider_cannot_enumerate_members(
    ws_ctx: WorkspaceTestContext,
) -> None:
    """Outsiders attempting to remove members must receive 403 regardless of target existence."""
    ws = await ws_ctx.service.create_workspace(
        ws_ctx.user_a,
        type("WorkspaceCreate", (), {"name": "Enumerate Test Space"})(),  # type: ignore[arg-type]
    )
    await ws_ctx.member_repo.add_member(ws.id, ws_ctx.user_b.id, role=WorkspaceRole.EDITOR)

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_c
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp_non_existent = await ac.delete(f"/api/v1/workspaces/{ws.id}/members/99999")
        assert resp_non_existent.status_code == 403
        assert resp_non_existent.json()["message"] == ERROR_PERMISSION_DENIED

        resp_existent = await ac.delete(f"/api/v1/workspaces/{ws.id}/members/{ws_ctx.user_b.id}")
        assert resp_existent.status_code == 403
        assert resp_existent.json()["message"] == ERROR_PERMISSION_DENIED


@pytest.mark.anyio
async def test_non_owner_member_can_see_workspace_in_list(
    ws_ctx: WorkspaceTestContext,
) -> None:
    """Non-owner members must see workspaces they belong to in list_workspaces with role."""
    ws = await ws_ctx.service.create_workspace(
        ws_ctx.user_a,
        type("WorkspaceCreate", (), {"name": "Shared Member Space"})(),  # type: ignore[arg-type]
    )
    await ws_ctx.member_repo.add_member(ws.id, ws_ctx.user_b.id, role=WorkspaceRole.EDITOR)

    app.dependency_overrides[get_current_user] = lambda: ws_ctx.user_b
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/api/v1/workspaces")
        assert resp.status_code == 200
        data = resp.json()
        assert any(item["id"] == ws.id and item["role"] == "EDITOR" for item in data["items"])


def test_workspace_repository_sql_query_compilation() -> None:
    """Verify that real Workspace and WorkspaceMember repository SQL queries compile correctly."""
    from sqlalchemy import or_
    from sqlalchemy.dialects import mysql

    member_subquery = (
        select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == 42).scalar_subquery()
    )
    condition = or_(
        Workspace.owner_id == 42,
        Workspace.id.in_(member_subquery),
    )
    ws_query = select(Workspace).where(condition)
    ws_sql = str(ws_query.compile(dialect=mysql.dialect()))
    assert "workspaces.owner_id" in ws_sql
    assert "workspace_members.workspace_id" in ws_sql

    roles_query = select(WorkspaceMember.workspace_id, WorkspaceMember.role).where(
        WorkspaceMember.workspace_id.in_([1, 2, 3]),
        WorkspaceMember.user_id == 42,
    )
    roles_sql = str(roles_query.compile(dialect=mysql.dialect()))
    assert "workspace_members.workspace_id IN" in roles_sql
    assert "workspace_members.user_id =" in roles_sql


@pytest.mark.anyio
async def test_real_workspace_and_member_repository_integration() -> None:
    """Test real repository operations against MySQL when available; skip if offline."""
    settings = get_settings()
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
        async with session_factory() as probe:
            await probe.execute(text("SELECT 1"))
            await probe.execute(text("SELECT id FROM users LIMIT 1"))
            await probe.execute(text("SELECT id FROM workspaces LIMIT 1"))
            await probe.execute(text("SELECT id FROM workspace_members LIMIT 1"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"MySQL unavailable or unmigrated for repository test: {exc}")

    async with session_factory() as session:
        try:
            ws_repo = WorkspaceRepository(session)
            member_repo = WorkspaceMemberRepository(session)

            user_ids = list(
                (await session.execute(text("SELECT id FROM users ORDER BY id ASC LIMIT 2")))
                .scalars()
                .all()
            )
            if len(user_ids) < 2:
                pytest.skip("Integration test requires at least 2 users in the test database")

            test_uid, test_member_uid = user_ids[0], user_ids[1]
            created_ws = await ws_repo.create(
                name=f"Repo-Test-{uuid.uuid4().hex[:8]}",
                owner_id=test_uid,
            )
            await session.flush()

            await member_repo.add_member(
                workspace_id=created_ws.id,
                user_id=test_member_uid,
                role=WorkspaceRole.EDITOR,
            )
            await session.flush()

            member_workspaces = await ws_repo.list_for_user(test_member_uid, page=1, limit=10)
            assert any(w.id == created_ws.id for w in member_workspaces.items)

            roles = await member_repo.get_roles_by_workspace_ids(
                [created_ws.id],
                test_member_uid,
            )
            assert roles.get(created_ws.id) == WorkspaceRole.EDITOR

            await ws_repo.delete(created_ws.id)
            await session.flush()
        finally:
            await session.rollback()
            await engine.dispose()
