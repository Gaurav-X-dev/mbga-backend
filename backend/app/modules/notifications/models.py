"""Per-user read state for notifications.

The notifications themselves are the existing `notification_outbox` rows - one row per
event, not one per reader. Spec §15 says all staff share the merchant bucket, so a merchant
event is written once and read by everyone.

Read state, though, is **per user**. A manager opening "New order received" must not mark it
read for the accountant who has not seen it yet. Absence of a row means unread, so marking
one read is an insert and nothing has to be back-filled for users who existed before.
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class NotificationRead(Base):
    __tablename__ = "notification_reads"
    __table_args__ = (
        # The list screen's query: this user's read rows for the notifications on screen.
        Index("ix_notification_reads_user", "user_id", "notification_id"),
    )

    # Composite key: one row per user per notification, so marking read twice is harmless.
    notification_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
