"""Notification service for asynchronous background dispatch of task events."""

from typing import Any

from loguru import logger

from app.models.enums import TaskStatus


class NotificationService:
    """Service handling task assignment and status transition notifications."""

    def __init__(self) -> None:
        self.dispatched_notifications: list[dict[str, Any]] = []

    async def send_task_assignment_notification(
        self,
        assignee_email: str,
        assignee_name: str,
        task_title: str,
        project_name: str,
        assigner_name: str,
    ) -> None:
        """Dispatch notification when a task is assigned to a workspace member."""
        payload = {
            "type": "task_assigned",
            "to": assignee_email,
            "assignee_name": assignee_name,
            "task_title": task_title,
            "project_name": project_name,
            "assigner_name": assigner_name,
        }
        self.dispatched_notifications.append(payload)
        logger.info(
            "Notification sent: Task '{}' in project '{}' assigned to {} ({}) by {}",
            task_title,
            project_name,
            assignee_name,
            assignee_email,
            assigner_name,
        )

    async def send_task_status_changed_notification(
        self,
        recipient_emails: list[str],
        task_title: str,
        project_name: str,
        old_status: TaskStatus,
        new_status: TaskStatus,
        updater_name: str,
    ) -> None:
        """Dispatch notification when a task changes status."""
        payload = {
            "type": "task_status_changed",
            "recipients": recipient_emails,
            "task_title": task_title,
            "project_name": project_name,
            "old_status": old_status.value,
            "new_status": new_status.value,
            "updater_name": updater_name,
        }
        self.dispatched_notifications.append(payload)
        logger.info(
            "Notification sent: Task '{}' in project '{}' status changed from {} to {} by {}. Recipients: {}",
            task_title,
            project_name,
            old_status.value,
            new_status.value,
            updater_name,
            ", ".join(recipient_emails),
        )

    def clear(self) -> None:
        """Clear dispatched notifications list for test isolation."""
        self.dispatched_notifications.clear()
