"""The notification outbox table.

Lives in shared rather than in the customers module because every later slice (orders,
dispatch, payments, stock) writes the same kind of row, and the notification module will
read them all from one place.
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class NotificationOutbox(Base):
    """Events the notification module will deliver once it exists (spec 18.8).

    Written inside the same transaction as the business change, so an approval and its
    "Account approved" notification cannot disagree about whether they happened. Nothing
    delivers these rows yet; that is the notification slice's job.
    """

    __tablename__ = "notification_outbox"
    __table_args__ = (
        Index("ix_notification_outbox_pending", "delivered_at", "created_at"),
        UniqueConstraint(
            "event_type", "entity_type", "entity_id", "recipient_kind", "recipient_id",
            name="uq_notification_outbox_event",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    # "customer" or "merchant" - who the message is addressed to.
    recipient_kind: Mapped[str] = mapped_column(String(20))
    recipient_id: Mapped[str] = mapped_column(String(36), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(36))
    title: Mapped[str] = mapped_column(String(180))
    body: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20), default="INFO")
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
