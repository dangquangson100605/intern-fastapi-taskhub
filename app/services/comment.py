"""Comment service managing comment creation, chronological retrieval, and author authorization."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    RESOURCE_COMMENT,
    RESOURCE_TASK,
)
from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.core.messages import (
    ERROR_CANNOT_DELETE_OTHERS_COMMENT,
    ERROR_CANNOT_UPDATE_OTHERS_COMMENT,
    ERROR_PROJECT_ARCHIVED,
    SUCCESS_COMMENT_DELETED,
)
from app.models.enums import ProjectStatus, UserRole, WorkspaceRole
from app.models.user import User
from app.repositories.comment import CommentRepository
from app.repositories.task import TaskRepository
from app.schemas.comment import CommentCreate, CommentResponse, CommentUpdate
from app.schemas.common import MessageResponse, PaginatedResponse, PaginationParams
from app.services.policies import ensure_write_access


class CommentService:
    """Service encapsulating task comment lifecycle, permissions, and author checks."""

    def __init__(
        self,
        session: AsyncSession,
        comment_repo: CommentRepository,
        task_repo: TaskRepository,
    ) -> None:
        self.session = session
        self.comment_repo = comment_repo
        self.task_repo = task_repo

    async def create_comment(
        self,
        task_id: int,
        current_user: User,
        data: CommentCreate,
    ) -> CommentResponse:
        """Create a new comment on a task enforcing write permissions and active project status."""
        resolved = await self.task_repo.get_with_project_and_workspace_role(
            task_id=task_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException(RESOURCE_TASK, task_id)

        _, project, role = resolved
        ensure_write_access(
            role=role,
            project=project,
            is_admin=current_user.role == UserRole.ADMIN,
            not_found_exc=NotFoundException(RESOURCE_TASK, task_id),
        )

        comment = await self.comment_repo.create_comment(
            task_id=task_id,
            author_id=current_user.id,
            content=data.content,
        )
        await self.session.commit()
        await self.session.refresh(comment, attribute_names=["author"])
        return CommentResponse.model_validate(comment)

    async def list_comments(
        self,
        task_id: int,
        current_user: User,
        pagination: PaginationParams,
    ) -> PaginatedResponse[CommentResponse]:
        """Fetch paginated comments for a task ordered by creation time ascending."""
        resolved = await self.task_repo.get_with_project_and_workspace_role(
            task_id=task_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException(RESOURCE_TASK, task_id)

        _, _, role = resolved
        if current_user.role != UserRole.ADMIN and role is None:
            raise NotFoundException(RESOURCE_TASK, task_id)

        result = await self.comment_repo.list_by_task(task_id, pagination)
        return PaginatedResponse[CommentResponse](
            items=[CommentResponse.model_validate(c) for c in result.items],
            total=result.total,
            page=result.page,
            limit=result.limit,
            total_pages=result.total_pages,
        )

    async def update_comment(
        self,
        comment_id: int,
        current_user: User,
        data: CommentUpdate,
    ) -> CommentResponse:
        """Update comment content ensuring only author or admin can update and project is active."""
        resolved = await self.comment_repo.get_with_task_and_workspace_role(
            comment_id=comment_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException(RESOURCE_COMMENT, comment_id)

        comment, _, project, role = resolved
        is_admin = current_user.role == UserRole.ADMIN
        if not is_admin and role is None:
            raise NotFoundException(RESOURCE_COMMENT, comment_id)

        is_author = comment.author_id == current_user.id
        if not (is_admin or is_author):
            raise ForbiddenException(ERROR_CANNOT_UPDATE_OTHERS_COMMENT)

        if project.status == ProjectStatus.ARCHIVED:
            raise ConflictException(ERROR_PROJECT_ARCHIVED)

        comment.content = data.content
        await self.session.commit()
        await self.session.refresh(comment, attribute_names=["author"])
        return CommentResponse.model_validate(comment)

    async def delete_comment(
        self,
        comment_id: int,
        current_user: User,
    ) -> MessageResponse:
        """Delete comment ensuring caller identity is checked before project archive check."""
        resolved = await self.comment_repo.get_with_task_and_workspace_role(
            comment_id=comment_id,
            user_id=current_user.id,
        )
        if resolved is None:
            raise NotFoundException(RESOURCE_COMMENT, comment_id)

        comment, _, project, role = resolved
        is_admin = current_user.role == UserRole.ADMIN
        if not is_admin and role is None:
            raise NotFoundException(RESOURCE_COMMENT, comment_id)

        is_author = comment.author_id == current_user.id
        is_owner = role == WorkspaceRole.OWNER

        if not (is_admin or is_owner or is_author):
            raise ForbiddenException(ERROR_CANNOT_DELETE_OTHERS_COMMENT)

        if project.status == ProjectStatus.ARCHIVED:
            raise ConflictException(ERROR_PROJECT_ARCHIVED)

        await self.comment_repo.delete(comment.id)
        await self.session.commit()
        return MessageResponse(message=SUCCESS_COMMENT_DELETED)
