"""Comment API endpoints for creating, listing, and author-authorized deletion of comments."""

from fastapi import APIRouter, status

from app.core.dependencies import CommentServiceDep, CurrentUser
from app.schemas.comment import CommentCreate, CommentResponse
from app.schemas.common import MessageResponse

router = APIRouter(tags=["Comments"])


@router.post(
    "/tasks/{task_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a comment on a task",
    description="Post a comment on a task. Requires write role (OWNER, EDITOR) and active project status.",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        404: {"description": "Task not found"},
        409: {"description": "Project is archived"},
        422: {"description": "Validation error (empty or content too long)"},
    },
)
async def create_comment(
    task_id: int,
    data: CommentCreate,
    current_user: CurrentUser,
    service: CommentServiceDep,
) -> CommentResponse:
    """Post a comment on a task."""
    return await service.create_comment(
        task_id=task_id,
        current_user=current_user,
        data=data,
    )


@router.get(
    "/tasks/{task_id}/comments",
    response_model=list[CommentResponse],
    status_code=status.HTTP_200_OK,
    summary="List comments on a task",
    description="Retrieve all comments for a task ordered chronologically by created_at ascending.",
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "Task not found"},
    },
)
async def list_comments(
    task_id: int,
    current_user: CurrentUser,
    service: CommentServiceDep,
) -> list[CommentResponse]:
    """List comments on a task."""
    return await service.list_comments(
        task_id=task_id,
        current_user=current_user,
    )


@router.delete(
    "/comments/{comment_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete a comment",
    description="Delete a comment. Only the comment author, workspace owner, or admin can delete.",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied (cannot delete someone else's comment)"},
        404: {"description": "Comment not found"},
        409: {"description": "Project is archived"},
    },
)
async def delete_comment(
    comment_id: int,
    current_user: CurrentUser,
    service: CommentServiceDep,
) -> MessageResponse:
    """Delete a comment."""
    return await service.delete_comment(
        comment_id=comment_id,
        current_user=current_user,
    )
