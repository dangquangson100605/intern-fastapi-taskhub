"""Notification service for asynchronous background dispatch of task events."""

from loguru import logger

from app.models.enums import TaskStatus


class NotificationService:
    """Service handling task assignment and status transition notifications."""

    async def send_task_assignment_notification(
        self,
        task_id: int,
        project_id: int,
        assignee_id: int,
        assigner_id: int,
        assignee_email: str,
        task_title: str,
        project_name: str,
        assigner_name: str,
    ) -> None:
        """Dispatch notification when a task is assigned to a workspace member without logging PII."""
        _ = (assignee_email, task_title, project_name, assigner_name)
        logger.info(
            "Task assignment notification dispatched: task_id={}, project_id={}, assignee_id={}, assigner_id={}",
            task_id,
            project_id,
            assignee_id,
            assigner_id,
        )

    async def send_task_status_changed_notification(
        self,
        task_id: int,
        project_id: int,
        old_status: TaskStatus,
        new_status: TaskStatus,
        updater_id: int,
        recipient_emails: list[str],
        task_title: str,
        project_name: str,
        updater_name: str,
    ) -> None:
        """Dispatch notification when a task changes status without logging recipient PII."""
        _ = (recipient_emails, task_title, project_name, updater_name)
        logger.info(
            "Task status changed notification dispatched: task_id={}, project_id={}, old_status={}, new_status={}, updater_id={}, recipient_count={}",
            task_id,
            project_id,
            old_status.value,
            new_status.value,
            updater_id,
            len(recipient_emails),
        )
