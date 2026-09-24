"""Service layer for notifications."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.schemas import NotificationResponse


def notification_to_response(n: Notification) -> NotificationResponse:
    return NotificationResponse(
        id=n.id,
        type=n.type,
        title=n.title,
        subtitle=n.subtitle,
        createdAt=n.created_at.isoformat(),
        isRead=n.is_read,
    )


class NotificationService:
    def __init__(self, repository: NotificationRepository, session: AsyncSession) -> None:
        self.repository = repository
        self.session = session

    async def list_notifications(self, user_id: str) -> list[dict]:
        notifications = await self.repository.list_for_user(user_id)
        return [notification_to_response(n).model_dump(by_alias=True) for n in notifications]

    async def mark_as_read(self, notification_id: str, user_id: str) -> None:
        notification = await self.repository.get_by_id_for_user(notification_id, user_id)
        if notification is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": "Notification not found."},
            )
        notification.is_read = True
        await self.session.commit()
