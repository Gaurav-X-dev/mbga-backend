"""Delivery slip tables (spec §3.12, §10).

A slip is a **copy** of what the order said at the moment the van was loaded, not a live view
of it. Items, address, site name and customer name are all copied onto the slip and its lines,
for the same reason an order copies its prices: a delivery is a physical event, and a slip has
to keep saying what actually went out on the van even after the customer has been renamed, the
delivery site edited, or the order's own lines examined in a dispute a year later.

What is *not* copied is money. A slip carries no prices at all - it is a loading and handover
document, and the invoice is raised off the order. Putting a total on the slip would create a
second number that has to agree with the order's, and eventually would not.

Three tables:

* `delivery_slips` - the slip itself, its vehicle and crew, its status and its timestamps.
* `delivery_slip_items` - the cylinders on it, one row per type.
* `delivery_number_sequences` - the per-merchant counter behind `DS-0148`.
"""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class DeliverySlip(Base):
    __tablename__ = "delivery_slips"
    __table_args__ = (
        UniqueConstraint("merchant_id", "slip_number", name="uq_delivery_slips_merchant_number"),
        # The Delivery & Dispatch list: this merchant, filtered by status, newest scheduled first.
        Index("ix_delivery_slips_merchant_status_scheduled", "merchant_id", "status", "scheduled_date"),
        # "Which slip is this order on?" - asked by the order detail screen and by invoicing.
        Index("ix_delivery_slips_order", "order_id"),
        # The driver's own list on the delivery app, once that screen exists.
        Index("ix_delivery_slips_driver_status", "driver_user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Readable and sequential per merchant (`DS-0148`). Quoted on the phone and printed on the
    # slip, so it is short and has no month segment. Never used for authorisation - it is
    # guessable by design, so every lookup still applies the tenancy filter.
    slip_number: Mapped[str] = mapped_column(String(30), index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)

    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    # Copied so the list renders without joining orders, and still reads correctly afterwards.
    order_number: Mapped[str] = mapped_column(String(30))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"), index=True)
    customer_name: Mapped[str] = mapped_column(String(160))
    # What the app searches on, alongside the numbers above (spec §10.1).
    customer_mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Where the van is going, copied from the order - which itself copied it from the site.
    delivery_site_name: Mapped[str] = mapped_column(String(160))
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address_state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address_pincode: Mapped[str | None] = mapped_column(String(6), nullable=True)

    # "4 × 19 KG · 6 × 5 KG". Display only, built at creation so the list needs no lines.
    items_summary: Mapped[str] = mapped_column(String(255))
    cylinders_allocated: Mapped[int] = mapped_column(Integer)

    vehicle_number: Mapped[str] = mapped_column(String(20))
    # The crew. `driver_user_id` is what makes the delivery app's notifications work: it is the
    # user the "new delivery assigned" event is addressed to. Nullable because a merchant may
    # run a hired van whose driver has no account, and a slip must still be raisable for it -
    # in which case nobody is notified and the office tells the driver directly.
    driver_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    driver_name: Mapped[str] = mapped_column(String(160))
    helper_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    helper_name: Mapped[str | None] = mapped_column(String(160), nullable=True)

    # A calendar day, not an instant: a van goes out on a date, and there is no delivery slot
    # to carry a time of day.
    scheduled_date: Mapped[date] = mapped_column(Date)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 0 until the delivery is confirmed (spec §3.12). `pendingPickup` is derived from this and
    # `cylinders_allocated` rather than stored, so the two can never disagree.
    empties_collected: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    confirmation_method: Mapped[str] = mapped_column(String(20))
    # The proof-of-delivery code, hashed. Never stored in the clear: it is read out at a gate,
    # and a plain column would be a shared secret sitting in the table that the whole office
    # can query. Null when the method is NONE, or once the slip is confirmed and it is spent.
    confirmation_code_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confirmation_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    status: Mapped[str] = mapped_column(String(20), index=True)
    # Why a slip failed. Read by whoever reschedules it, so it is free text rather than a code.
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Who raised it, and who dispatched and confirmed it. Denormalised display names, resolved
    # from the session and never from the body, so the slip still says who did what after the
    # person has left.
    created_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    dispatched_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    confirmed_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DeliverySlipItem(Base):
    """One cylinder type on one slip: what the van is supposed to be carrying."""

    __tablename__ = "delivery_slip_items"
    __table_args__ = (
        # One row per type per slip. The order's own lines are already merged by type, and a
        # slip is built from them, so a duplicate here would be a bug rather than a big load.
        UniqueConstraint("slip_id", "cylinder_type", name="uq_delivery_slip_items_slip_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slip_id: Mapped[str] = mapped_column(ForeignKey("delivery_slips.id"), index=True)
    cylinder_type: Mapped[str] = mapped_column(String(40))
    quantity: Mapped[int] = mapped_column(Integer)
    # Display order, so the slip lists cylinders the way the order did.
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class DeliveryNumberSequence(Base):
    """Concurrency-safe counter behind `DS-0148`.

    One row per merchant, incremented under `SELECT ... FOR UPDATE`, exactly as
    `OrderNumberSequence` and `customers/codes.py` already do. Unlike the order counter this
    one does not reset monthly: the spec's slip number carries no month, and a merchant's slip
    numbers running continuously is what makes "DS-0148" a thing staff can file by.
    """

    __tablename__ = "delivery_number_sequences"

    prefix: Mapped[str] = mapped_column(String(80), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer)
    # Kept so an operator can see the counter is live without reading the slips table.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
