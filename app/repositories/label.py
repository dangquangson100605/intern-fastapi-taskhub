"""Label repository handling label queries, workspace joins, and task association."""

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import CursorResult, and_, delete, func, insert, select

from app.core.constants import DEFAULT_LABEL_COLOR
from app.models.enums import WorkspaceRole
from app.models.label import Label, task_labels
from app.models.project import Project
from app.models.workspace import Workspace, WorkspaceMember
from app.repositories.base import BaseRepository


class LabelRepository(BaseRepository[Label]):
    """Repository managing Label entity persistence and task association."""

    model = Label

    async def create_label(
        self,
        project_id: int,
        name: str,
        color: str = DEFAULT_LABEL_COLOR,
    ) -> Label:
        """Insert and flush a new label record."""
        instance = self.model(
            project_id=project_id,
            name=name,
            color=color,
        )
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def get_with_project_and_workspace_role(
        self,
        label_id: int,
        user_id: int,
    ) -> tuple[Label, Project, WorkspaceRole | None] | None:
        """Fetch label and resolve project and caller workspace role in a single joined query."""
        query = (
            select(Label, Project, WorkspaceMember.role, Workspace.owner_id)
            .join(Project, Label.project_id == Project.id)
            .join(Workspace, Project.workspace_id == Workspace.id)
            .outerjoin(
                WorkspaceMember,
                and_(
                    WorkspaceMember.workspace_id == Workspace.id,
                    WorkspaceMember.user_id == user_id,
                ),
            )
            .where(Label.id == label_id)
        )
        result = await self.session.execute(query)
        row = result.first()
        if row is None:
            return None

        label, project, member_role, owner_id = row
        effective_role = WorkspaceRole.OWNER if owner_id == user_id else member_role
        return label, project, effective_role

    async def list_by_project(self, project_id: int) -> Sequence[Label]:
        """Fetch all labels belonging to a specific project ordered by id ascending."""
        query = select(Label).where(Label.project_id == project_id).order_by(Label.id.asc())
        result = await self.session.execute(query)
        return result.scalars().all()

    async def list_by_workspace(self, workspace_id: int) -> Sequence[Label]:
        """Fetch all labels belonging to any project within a workspace."""
        query = (
            select(Label)
            .join(Project, Label.project_id == Project.id)
            .where(Project.workspace_id == workspace_id)
            .order_by(Label.id.asc())
        )
        result = await self.session.execute(query)
        return result.scalars().all()

    async def is_assigned_to_task(self, task_id: int, label_id: int) -> bool:
        """Check whether a task currently has the specified label attached."""
        query = (
            select(func.count())
            .select_from(task_labels)
            .where(
                and_(
                    task_labels.c.task_id == task_id,
                    task_labels.c.label_id == label_id,
                )
            )
        )
        result = await self.session.execute(query)
        count = result.scalar() or 0
        return count > 0

    async def assign_to_task(self, task_id: int, label_id: int) -> None:
        """Associate a label with a task in the task_labels junction table."""
        stmt = insert(task_labels).values(task_id=task_id, label_id=label_id)
        await self.session.execute(stmt)

    async def remove_from_task(self, task_id: int, label_id: int) -> bool:
        """Remove a label association from a task. Returns True if a row was deleted."""
        stmt = delete(task_labels).where(
            and_(
                task_labels.c.task_id == task_id,
                task_labels.c.label_id == label_id,
            )
        )
        result = await self.session.execute(stmt)
        cursor_result = cast(CursorResult[Any], result)
        return bool(cursor_result.rowcount > 0)

    async def list_by_task(self, task_id: int) -> Sequence[Label]:
        """Fetch all labels currently attached to a task."""
        query = (
            select(Label)
            .join(task_labels, Label.id == task_labels.c.label_id)
            .where(task_labels.c.task_id == task_id)
            .order_by(Label.id.asc())
        )
        result = await self.session.execute(query)
        return result.scalars().all()
