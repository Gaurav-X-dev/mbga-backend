"""Reading notifications (spec §15).

Which bucket an actor reads is the whole access model here:

* a **customer** reads events addressed to their own customer profile;
* **staff** read events addressed to their merchant - shared, because spec §15 says "all
  staff share the merchant bucket";
* a **driver** reads only what is addressed to them personally. They are not staff, so the
  merchant's bucket is not theirs: "New order received" is a job for the office, while
  "your delivery is ready to load" is for the person driving.

Everyone also reads anything addressed to them personally (`recipient_kind = user`).

Read state is per user, not per bucket. Absence of a `notification_reads` row means unread,
so marking one read is an insert and nothing needs back-filling for users who already exist.
"""

from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.constants import RecipientKind, category_of, reference_of
from app.modules.notifications.models import NotificationRead
from app.modules.notifications.schemas import AppNotification, UnreadCount
from app.shared.business.actor import BusinessActor
from app.shared.exceptions.api_error import ApiError
from app.shared.notifications.models import NotificationOutbox

#: How many rows the screen gets at once. The apps do not paginate in Phase 1 (spec §1), so
#: this is a safety bound rather than a page - a two-year-old notification helps nobody.
MAX_ROWS = 200


class NotificationService:
    def __init__(self, session: AsyncSession, actor: BusinessActor) -> None:
        self.session = session
        self.actor = actor

    async def list(self, *, unread_only: bool = False) -> list[AppNotification]:
        """This actor's notifications, newest first."""
        rows = list(
            await self.session.scalars(
                self._scoped().order_by(
                    NotificationOutbox.created_at.desc(), NotificationOutbox.id.desc()
                ).limit(MAX_ROWS)
            )
        )
        read_ids = await self._read_ids([row.id for row in rows])
        views = [_view(row, row.id in read_ids) for row in rows]
        return [view for view in views if not view.read] if unread_only else views

    async def get(self, notification_id: str) -> AppNotification:
        row = await self.session.scalar(
            self._scoped().where(NotificationOutbox.id == notification_id)
        )
        if row is None:
            # Someone else's notification is not found, never forbidden - the id would
            # otherwise confirm that a notification exists for another merchant.
            raise ApiError("NOTIFICATION_NOT_FOUND", status.HTTP_404_NOT_FOUND)
        return _view(row, row.id in await self._read_ids([row.id]))

    async def unread_count(self) -> UnreadCount:
        """The bell badge, as one count rather than a list the app has to filter."""
        read = select(NotificationRead.notification_id).where(
            NotificationRead.user_id == self.actor.user_id
        )
        total = await self.session.scalar(
            select(func.count()).select_from(
                self._scoped().where(NotificationOutbox.id.not_in(read)).subquery()
            )
        )
        return UnreadCount(unread=int(total or 0))

    async def mark_read(self, notification_id: str) -> None:
        """Idempotent: marking an already-read notification read again is not an error."""
        await self.get(notification_id)
        await self._mark([notification_id])
        await self.session.commit()

    async def mark_all_read(self) -> None:
        ids = list(await self.session.scalars(self._scoped().with_only_columns(NotificationOutbox.id)))
        if ids:
            await self._mark(ids)
        await self.session.commit()

    async def _mark(self, ids: list[str]) -> None:
        """Insert read rows, ignoring the ones already there.

        `INSERT ... ON DUPLICATE KEY UPDATE` rather than a read-then-write: two taps on the
        same row from two devices would otherwise race on the primary key.
        """
        now = datetime.now(UTC)
        statement = mysql_insert(NotificationRead).values(
            [
                {"notification_id": notification_id, "user_id": self.actor.user_id, "read_at": now}
                for notification_id in ids
            ]
        )
        await self.session.execute(
            statement.on_duplicate_key_update(read_at=statement.inserted.read_at)
        )

    def _scoped(self) -> Select:
        """Every notification this actor may read, and nothing else."""
        buckets = [
            and_(
                NotificationOutbox.recipient_kind == RecipientKind.USER.value,
                NotificationOutbox.recipient_id == self.actor.user_id,
            )
        ]
        if self.actor.is_customer:
            # A customer with no profile yet (mid-registration) has no bucket of their own;
            # they still see anything addressed to them personally.
            if self.actor.customer_id:
                buckets.append(
                    and_(
                        NotificationOutbox.recipient_kind == RecipientKind.CUSTOMER.value,
                        NotificationOutbox.recipient_id == self.actor.customer_id,
                    )
                )
        elif self.actor.merchant_id:
            buckets.append(
                and_(
                    NotificationOutbox.recipient_kind == RecipientKind.MERCHANT.value,
                    NotificationOutbox.recipient_id == self.actor.merchant_id,
                )
            )
        return select(NotificationOutbox).where(or_(*buckets))

    async def _read_ids(self, ids: list[str]) -> set[str]:
        if not ids:
            return set()
        return set(
            await self.session.scalars(
                select(NotificationRead.notification_id).where(
                    NotificationRead.user_id == self.actor.user_id,
                    NotificationRead.notification_id.in_(ids),
                )
            )
        )


def _view(row: NotificationOutbox, read: bool) -> AppNotification:
    reference = reference_of(row.entity_type)
    return AppNotification(
        id=row.id,
        title=row.title,
        message=row.body,
        severity=row.severity or "INFO",
        category=category_of(row.event_type, row.entity_type),
        created_at=row.created_at,
        read=read,
        reference_type=reference,
        reference_id=row.entity_id if reference else None,
    )
