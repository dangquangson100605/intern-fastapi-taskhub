"""Task repository handling queries, filtering, and single-join authorization."""

import math
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, func, select
from sqlalchemy.orm import selectinload

from app.models.enums import TaskPriority, TaskStatus, WorkspaceRole
from app.models.project import Project
from app.models.task import Task
from app.models.workspace import Workspace, WorkspaceMember
from app.repositories.base import BaseRepository, PaginationResult
from app.schemas.common import PaginationParams


class TaskRepository(BaseRepository[Task]):
    """Repository managing Task entity queries and lifecycle."""

    model = Task

    async def get_with_project_and_workspace_role(
        self,
        task_id: int,
        user_id: int,
    ) -> tuple[Task, Project, WorkspaceRole | None] | None:
        """Fetch task and resolve project and caller workspace role in a single joined query."""
        query = (
            select(Task, Project, WorkspaceMember.role, Workspace.owner_id)
            .join(Project, Task.project_id == Project.id)
            .join(Workspace, Project.workspace_id == Workspace.id)
            .outerjoin(
                WorkspaceMember,
                and_(
                    WorkspaceMember.workspace_id == Workspace.id,
                    WorkspaceMember.user_id == user_id,
                ),
            )
            .where(Task.id == task_id)
            .options(selectinload(Task.assignee), selectinload(Task.creator))
        )
        result = await self.session.execute(query)
        row = result.first()
        if row is None:
            return None

        task, project, member_role, owner_id = row
        effective_role = WorkspaceRole.OWNER if owner_id == user_id else member_role
        return task, project, effective_role

    async def list_by_project(
        self,
        project_id: int,
        pagination: PaginationParams,
        statuses: Sequence[TaskStatus] | None = None,
        priorities: Sequence[TaskPriority] | None = None,
        assignee_id: int | None = None,
    ) -> PaginationResult[Task]:
        """Fetch filtered and paginated tasks for a project avoiding N+1 via selectinload."""
        conditions = [Task.project_id == project_id]
        if statuses:
            conditions.append(Task.status.in_(statuses))
        if priorities:
            conditions.append(Task.priority.in_(priorities))
        if assignee_id is not None:
            conditions.append(Task.assignee_id == assignee_id)

        count_query = select(func.count(Task.id)).where(*conditions)
        total_result = await self.session.execute(count_query)
        total = total_result.scalar() or 0

        data_query = (
            select(Task)
            .where(*conditions)
            .options(selectinload(Task.assignee), selectinload(Task.creator))
            .order_by(Task.id.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
        result = await self.session.execute(data_query)
        items = list(result.scalars().all())

        return PaginationResult(
            items=items,
            total=total,
            page=pagination.page,
            limit=pagination.limit,
            total_pages=math.ceil(total / pagination.limit) if pagination.limit > 0 else 0,
        )

    async def create_task(
        self,
        project_id: int,
        created_by: int,
        title: str,
        description: str | None = None,
        priority: TaskPriority = TaskPriority.MEDIUM,
        assignee_id: int | None = None,
        due_date: datetime | None = None,
    ) -> Task:
        """Insert a new task initialized to TODO status."""
        instance = self.model(
            project_id=project_id,
            created_by=created_by,
            title=title,
            description=description,
            status=TaskStatus.TODO,
            priority=priority,
            assignee_id=assignee_id,
            due_date=due_date,
        )
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance, attribute_names=["creator"])
        return instance
