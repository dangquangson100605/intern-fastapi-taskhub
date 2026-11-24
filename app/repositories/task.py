"""Task repository handling queries, dynamic filtering, sorting, and single-join authorization."""

import math
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import selectinload

from app.models.enums import SortOrder, TaskPriority, TaskSortBy, TaskStatus, WorkspaceRole
from app.models.label import task_labels
from app.models.project import Project
from app.models.task import Task
from app.models.workspace import Workspace, WorkspaceMember
from app.repositories.base import BaseRepository, PaginationResult
from app.schemas.common import PaginationParams


class TaskRepository(BaseRepository[Task]):
    """Repository managing Task entity queries, advanced filters, sorting, and lifecycle."""

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
        search: str | None = None,
        statuses: Sequence[TaskStatus] | None = None,
        priorities: Sequence[TaskPriority] | None = None,
        assignee_id: int | None = None,
        due_date_from: datetime | None = None,
        due_date_to: datetime | None = None,
        label_id: int | None = None,
        sort_by: TaskSortBy = TaskSortBy.CREATED_AT,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> PaginationResult[Task]:
        """Fetch filtered, sorted, and paginated tasks for a project avoiding N+1 via selectinload."""
        conditions: list[Any] = [Task.project_id == project_id]

        if search:
            escaped = (
                search.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            pattern = f"%{escaped}%"
            conditions.append(
                or_(
                    Task.title.ilike(pattern),
                    Task.description.ilike(pattern),
                )
            )

        if statuses:
            conditions.append(Task.status.in_(statuses))

        if priorities:
            conditions.append(Task.priority.in_(priorities))

        if assignee_id is not None:
            conditions.append(Task.assignee_id == assignee_id)

        if due_date_from is not None:
            conditions.append(Task.due_date >= due_date_from)

        if due_date_to is not None:
            conditions.append(Task.due_date <= due_date_to)

        if label_id is not None:
            label_subquery = select(task_labels.c.task_id).where(task_labels.c.label_id == label_id)
            conditions.append(Task.id.in_(label_subquery))

        count_query = select(func.count(Task.id)).where(*conditions)
        total_result = await self.session.execute(count_query)
        total = total_result.scalar() or 0

        sort_expr: Any
        if sort_by == TaskSortBy.PRIORITY:
            priority_rank = case(
                (Task.priority == TaskPriority.LOW, 1),
                (Task.priority == TaskPriority.MEDIUM, 2),
                (Task.priority == TaskPriority.HIGH, 3),
                (Task.priority == TaskPriority.URGENT, 4),
                else_=0,
            )
            sort_expr = priority_rank
        elif sort_by == TaskSortBy.DUE_DATE:
            sort_expr = Task.due_date
        elif sort_by == TaskSortBy.TITLE:
            sort_expr = Task.title
        else:
            sort_expr = Task.created_at

        if sort_order == SortOrder.ASC:
            order_clause = [sort_expr.asc(), Task.id.asc()]
        else:
            order_clause = [sort_expr.desc(), Task.id.desc()]

        data_query = (
            select(Task)
            .where(*conditions)
            .options(selectinload(Task.assignee), selectinload(Task.creator))
            .order_by(*order_clause)
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
        return instance
