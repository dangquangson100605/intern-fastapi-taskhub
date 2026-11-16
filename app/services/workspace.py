"""Workspace service orchestrating workspace lifecycle, membership, and authorization."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.core.messages import (
    ERROR_CANNOT_DEMOTE_OR_REMOVE_WORKSPACE_OWNER,
    ERROR_INACTIVE_USER,
    ERROR_PERMISSION_DENIED,
    ERROR_WORKSPACE_MEMBER_ALREADY_EXISTS,
)
from app.models.enums import UserRole, WorkspaceRole
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.repositories.base import PaginationResult
from app.repositories.user import UserRepository
from app.repositories.workspace import WorkspaceRepository
from app.repositories.workspace_member import WorkspaceMemberRepository
from app.schemas.common import PaginatedResponse
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceMemberAdd,
    WorkspaceMemberUpdate,
    WorkspaceResponse,
    WorkspaceUpdate,
)


class WorkspaceService:
    """Service encapsulating workspace business rules, member access, and RBAC."""

    def __init__(
        self,
        session: AsyncSession,
        workspace_repo: WorkspaceRepository,
        member_repo: WorkspaceMemberRepository,
        user_repo: UserRepository,
    ) -> None:
        self.session = session
        self.workspace_repo = workspace_repo
        self.member_repo = member_repo
        self.user_repo = user_repo

    async def create_workspace(
        self,
        current_user: User,
        data: WorkspaceCreate,
    ) -> WorkspaceResponse:
        """Create a new workspace and automatically register the creator as OWNER."""
        workspace = await self.workspace_repo.create(
            name=data.name,
            owner_id=current_user.id,
        )
        await self.member_repo.add_member(
            workspace_id=workspace.id,
            user_id=current_user.id,
            role=WorkspaceRole.OWNER,
        )
        await self.session.commit()
        await self.session.refresh(workspace)
        return WorkspaceResponse(
            id=workspace.id,
            name=workspace.name,
            owner_id=workspace.owner_id,
            role=WorkspaceRole.OWNER,
            created_at=workspace.created_at,
        )

    async def get_workspace(
        self,
        workspace_id: int,
        current_user: User,
    ) -> WorkspaceResponse:
        """Retrieve workspace details verifying that the caller has membership or admin rights."""
        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if workspace is None:
            raise NotFoundException("Workspace")

        if current_user.role == UserRole.ADMIN:
            member = await self.member_repo.get_member(workspace_id, current_user.id)
            user_role = (
                member.role
                if member is not None
                else (WorkspaceRole.OWNER if workspace.owner_id == current_user.id else None)
            )
            return WorkspaceResponse(
                id=workspace.id,
                name=workspace.name,
                owner_id=workspace.owner_id,
                role=user_role,
                created_at=workspace.created_at,
            )

        member = await self.member_repo.get_member(workspace_id, current_user.id)
        if member is None:
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        return WorkspaceResponse(
            id=workspace.id,
            name=workspace.name,
            owner_id=workspace.owner_id,
            role=member.role,
            created_at=workspace.created_at,
        )

    async def list_workspaces(
        self,
        current_user: User,
        page: int = 1,
        limit: int = 20,
    ) -> PaginatedResponse[WorkspaceResponse]:
        """List all workspaces accessible to the caller."""
        if current_user.role == UserRole.ADMIN:
            paginated = await self.workspace_repo.list_all_paginated(page=page, limit=limit)
        else:
            paginated = await self.workspace_repo.list_for_user(
                current_user.id, page=page, limit=limit
            )

        responses: list[WorkspaceResponse] = []
        for ws in paginated.items:
            member = await self.member_repo.get_member(ws.id, current_user.id)
            user_role = member.role if member is not None else None
            responses.append(
                WorkspaceResponse(
                    id=ws.id,
                    name=ws.name,
                    owner_id=ws.owner_id,
                    role=user_role,
                    created_at=ws.created_at,
                )
            )

        return PaginatedResponse[WorkspaceResponse](
            items=responses,
            total=paginated.total,
            page=paginated.page,
            limit=paginated.limit,
            total_pages=paginated.total_pages,
        )

    async def update_workspace(
        self,
        workspace_id: int,
        current_user: User,
        data: WorkspaceUpdate,
    ) -> WorkspaceResponse:
        """Update workspace details only if the caller is the OWNER or system ADMIN."""
        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if workspace is None:
            raise NotFoundException("Workspace")

        is_owner = workspace.owner_id == current_user.id
        is_admin = current_user.role == UserRole.ADMIN
        if not (is_owner or is_admin):
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        if data.name is not None:
            workspace.name = data.name

        await self.session.commit()
        await self.session.refresh(workspace)

        member = await self.member_repo.get_member(workspace_id, current_user.id)
        user_role = member.role if member is not None else (WorkspaceRole.OWNER if is_owner else None)
        return WorkspaceResponse(
            id=workspace.id,
            name=workspace.name,
            owner_id=workspace.owner_id,
            role=user_role,
            created_at=workspace.created_at,
        )

    async def delete_workspace(
        self,
        workspace_id: int,
        current_user: User,
    ) -> None:
        """Delete a workspace only if the caller is the OWNER or system ADMIN."""
        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if workspace is None:
            raise NotFoundException("Workspace")

        is_owner = workspace.owner_id == current_user.id
        is_admin = current_user.role == UserRole.ADMIN
        if not (is_owner or is_admin):
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        await self.workspace_repo.delete(workspace_id)
        await self.session.commit()

    async def list_members(
        self,
        workspace_id: int,
        current_user: User,
        page: int = 1,
        limit: int = 20,
    ) -> PaginationResult[WorkspaceMember]:
        """List workspace members ensuring caller is a member or system ADMIN."""
        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if workspace is None:
            raise NotFoundException("Workspace")

        if current_user.role != UserRole.ADMIN:
            member = await self.member_repo.get_member(workspace_id, current_user.id)
            if member is None:
                raise ForbiddenException(ERROR_PERMISSION_DENIED)

        return await self.member_repo.list_members(workspace_id, page=page, limit=limit)

    async def add_member(
        self,
        workspace_id: int,
        current_user: User,
        data: WorkspaceMemberAdd,
    ) -> WorkspaceMember:
        """Add a member to a workspace enforcing OWNER/ADMIN authorization and duplicate checks."""
        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if workspace is None:
            raise NotFoundException("Workspace")

        is_owner = workspace.owner_id == current_user.id
        is_admin = current_user.role == UserRole.ADMIN
        if not (is_owner or is_admin):
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        target_user = await self.user_repo.get_by_id(data.user_id)
        if target_user is None:
            raise NotFoundException("User", data.user_id)
        if not target_user.is_active:
            raise BadRequestException(ERROR_INACTIVE_USER)

        existing = await self.member_repo.get_member(workspace_id, data.user_id)
        if existing is not None:
            raise ConflictException(ERROR_WORKSPACE_MEMBER_ALREADY_EXISTS)

        try:
            member = await self.member_repo.add_member(
                workspace_id=workspace_id,
                user_id=data.user_id,
                role=data.role,
            )
            await self.session.commit()
            return member
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictException(ERROR_WORKSPACE_MEMBER_ALREADY_EXISTS) from exc

    async def update_member_role(
        self,
        workspace_id: int,
        target_user_id: int,
        current_user: User,
        data: WorkspaceMemberUpdate,
    ) -> WorkspaceMember:
        """Update a member's role preventing OWNER demotion and unauthorized changes."""
        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if workspace is None:
            raise NotFoundException("Workspace")

        is_owner = workspace.owner_id == current_user.id
        is_admin = current_user.role == UserRole.ADMIN
        if not (is_owner or is_admin):
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        target_member = await self.member_repo.get_member(workspace_id, target_user_id)
        if target_member is None:
            raise NotFoundException("Workspace member")

        if workspace.owner_id == target_user_id:
            raise BadRequestException(ERROR_CANNOT_DEMOTE_OR_REMOVE_WORKSPACE_OWNER)

        updated = await self.member_repo.update_role(
            workspace_id=workspace_id,
            user_id=target_user_id,
            role=data.role,
        )
        if updated is None:
            raise NotFoundException("Workspace member")

        await self.session.commit()
        return updated

    async def remove_member(
        self,
        workspace_id: int,
        target_user_id: int,
        current_user: User,
    ) -> None:
        """Remove a member ensuring owner protection and proper authorization."""
        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if workspace is None:
            raise NotFoundException("Workspace")

        target_member = await self.member_repo.get_member(workspace_id, target_user_id)
        if target_member is None:
            raise NotFoundException("Workspace member")

        if workspace.owner_id == target_user_id:
            raise BadRequestException(ERROR_CANNOT_DEMOTE_OR_REMOVE_WORKSPACE_OWNER)

        is_owner = workspace.owner_id == current_user.id
        is_admin = current_user.role == UserRole.ADMIN
        is_self = current_user.id == target_user_id
        if not (is_owner or is_admin or is_self):
            raise ForbiddenException(ERROR_PERMISSION_DENIED)

        await self.member_repo.remove_member(workspace_id, target_user_id)
        await self.session.commit()
