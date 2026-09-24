"""FastAPI router for Notifications domain (API Reference §9)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deliveries.dependencies import require_delivery_user
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.service import NotificationService
from app.shared.authorization.context import AuthContext
from app.shared.database.session import get_db_session
from app.shared.middleware.response_envelope import success_response

router = APIRouter(tags=["delivery-notifications"])


def get_notification_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> NotificationService:
    return NotificationService(NotificationRepository(session), session)


@router.get("/notifications")
async def list_notifications(
    auth: Annotated[AuthContext, Depends(require_delivery_user)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
):
    """GET /notifications — §9.1: Driver notifications list."""
    items = await service.list_notifications(user_id=auth.user_id)
    return success_response(items)


@router.patch("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    auth: Annotated[AuthContext, Depends(require_delivery_user)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
):
    """PATCH /notifications/{notificationId}/read — §9.2: Mark notification as read."""
    await service.mark_as_read(notification_id=notification_id, user_id=auth.user_id)
    return success_response(None)
