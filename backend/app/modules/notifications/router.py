"""Notification routes, mounted on the customer and merchant channels (spec §15).

Both channels mount the same handlers through `build_notification_router`, the way orders
and documents already do. No permission is required on either: spec §2.1 gives customers
none, and a staff member reading their own merchant's notifications is authorised by being
that merchant's staff - `NotificationService._scoped()` is what enforces it.

Route order matters: `/notifications/unread-count` and `/notifications/read-all` are
declared before `/notifications/{notificationId}`, or they would be matched as ids.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep, CustomerActorDep
from app.modules.notifications.schemas import AppNotification, UnreadCount
from app.modules.notifications.service import NotificationService
from app.shared.authorization.dependencies import require_login_channel
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

NotificationIdPath = Annotated[str, Path(alias="notificationId", max_length=36)]


def build_notification_router(channel: LoginChannel) -> APIRouter:
    """Build the `/notifications` routes for one channel."""
    is_customer = channel is LoginChannel.CUSTOMER
    router = APIRouter(prefix="/notifications", tags=[f"{channel.value.title()} Notifications"])

    channel_only = Depends(require_login_channel(channel))
    actor_dependency = CustomerActorDep if is_customer else ActorDep

    def build_service(
        actor: actor_dependency,
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> NotificationService:
        return NotificationService(session, actor)

    ServiceDep = Annotated[NotificationService, Depends(build_service)]

    @router.get(
        "",
        response_model=list[AppNotification],
        dependencies=[channel_only],
        responses=error_responses(401, 403),
        summary="Notifications",
    )
    async def list_notifications(
        service: ServiceDep,
        unread_only: Annotated[bool, Query(alias="unreadOnly", description="Only the ones not yet read.")] = False,
    ) -> list[AppNotification]:
        """Newest first.

        A customer sees their own; staff see their merchant's, shared across the team
        (spec §15). `read` is per user, so one person opening a notification does not hide
        it from the rest.
        """
        return await service.list(unread_only=unread_only)

    @router.get(
        "/unread-count",
        response_model=UnreadCount,
        dependencies=[channel_only],
        responses=error_responses(401, 403),
        summary="Unread count",
    )
    async def unread_count(service: ServiceDep) -> UnreadCount:
        """The bell badge, without fetching the list to count it."""
        return await service.unread_count()

    @router.post(
        "/read-all",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[channel_only],
        responses=error_responses(401, 403),
        summary="Mark all read",
    )
    async def mark_all_read(service: ServiceDep) -> Response:
        await service.mark_all_read()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get(
        "/{notificationId}",
        response_model=AppNotification,
        dependencies=[channel_only],
        responses=error_responses(401, 403, 404),
        summary="Notification detail",
    )
    async def notification_detail(
        service: ServiceDep, notification_id: NotificationIdPath
    ) -> AppNotification:
        """Someone else's notification is reported as 404, never 403."""
        return await service.get(notification_id)

    @router.post(
        "/{notificationId}/read",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[channel_only],
        responses=error_responses(401, 403, 404),
        summary="Mark read",
    )
    async def mark_read(service: ServiceDep, notification_id: NotificationIdPath) -> Response:
        """Idempotent - marking an already-read notification read again is not an error."""
        await service.mark_read(notification_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
