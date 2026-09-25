"""Order tables: the order, its lines, its status trail and the order-number counter.

Money is `BIGINT` whole rupees, per spec §1 ("Money | Integer whole rupees. No paise") and
the existing `app/shared/money` helpers. Pricing carries `DECIMAL(10,2)` because a per-kg
markup can legitimately hold paise; an order total cannot, so the rounding happens once, at
the boundary, and is recorded here as an integer.

Prices are **copied onto the line**, not joined to the price card. A price card changes
mid-month by design (that is what the pricing slice is for); an order must keep the price it
was placed at, or every historical total silently rewrites itself the next time a rate moves.

`id` is a UUID and `order_number` is the readable `ORD-2609-0151`, matching how
`customer_profiles` already separates `id` from `code`. The spec calls ids opaque strings;
the demo payload happens to show the same value in both fields.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
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


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("merchant_id", "order_number", name="uq_orders_merchant_number"),
        # The Orders tab: this merchant, newest first, optionally filtered by status.
        Index("ix_orders_merchant_status_placed", "merchant_id", "status", "placed_at"),
        # The customer app's own list, and the customer-detail history on the merchant side.
        Index("ix_orders_customer_placed", "customer_id", "placed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Readable and sequential per merchant (ORD-2609-0151). Never used for authorisation -
    # it is guessable by design, so every lookup still applies the tenancy filter.
    order_number: Mapped[str] = mapped_column(String(30), index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"), index=True)
    # Denormalised so the list renders without a join and still reads correctly after a
    # customer is renamed. `customer_name` is also what the search filter matches on.
    customer_name: Mapped[str] = mapped_column(String(160))
    customer_type: Mapped[str] = mapped_column(String(40))

    order_mode: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(20))

    # Industrial orders carry a site; retail orders use the registered address.
    delivery_site_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    delivery_site_name: Mapped[str] = mapped_column(String(160))
    # The address is copied, not joined: moving a delivery site must not rewrite where a
    # past order was actually delivered.
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address_state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address_pincode: Mapped[str | None] = mapped_column(String(6), nullable=True)

    total_cylinders: Mapped[int] = mapped_column(Integer)
    # "6 × 47.5 L · 2 × 47.5 V". Display only, built at placement so the list needs no lines.
    items_summary: Mapped[str] = mapped_column(String(255))
    # GST-inclusive total; subtotal and gst_amount are broken out of it, never added on top.
    total_amount: Mapped[int] = mapped_column(BigInteger)
    subtotal: Mapped[int] = mapped_column(BigInteger)
    gst_amount: Mapped[int] = mapped_column(BigInteger)
    gst_percent: Mapped[int] = mapped_column(Integer)
    # Which month's card priced this order. Kept for reconciliation, not for re-pricing.
    pricing_month_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    status: Mapped[str] = mapped_column(String(20), index=True)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # The cut-off exactly as it was evaluated at placement (spec §3.10 `cutoff`).
    cutoff_time: Mapped[str] = mapped_column(String(5))
    within_cutoff: Mapped[bool] = mapped_column(Boolean)
    # A calendar day, not an instant: a delivery has no time of day now that the slot is gone,
    # and storing one is what made it renderable five and a half hours out.
    scheduled_delivery_date: Mapped[date] = mapped_column(Date)
    cutoff_message: Mapped[str] = mapped_column(String(255))

    # Staff display name when placed from the merchant app; null for a customer's own order.
    created_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Filled by the delivery and invoicing slices when they land.
    delivery_slip_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    invoice_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrderItem(Base):
    """One cylinder type on one order, at the price it was sold for."""

    __tablename__ = "order_items"
    __table_args__ = (
        # Duplicate lines are merged before insert, so one type appears once per order.
        UniqueConstraint("order_id", "cylinder_type", name="uq_order_items_order_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    cylinder_type: Mapped[str] = mapped_column(String(40))
    quantity: Mapped[int] = mapped_column(Integer)
    # GST-inclusive, per cylinder, as resolved for this customer at placement.
    unit_price: Mapped[int] = mapped_column(BigInteger)
    line_total: Mapped[int] = mapped_column(BigInteger)
    # True when a per-customer override was applied rather than the tier price. Recorded so
    # a disputed invoice can be explained without replaying the price history.
    price_overridden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Display order on the order, so the app renders lines the way they were entered.
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class OrderStatusHistory(Base):
    """Append-only trail behind the tracking timeline (spec §3.10 `statusHistory`).

    A table rather than a JSON column: this is what a delivery report and a dispute both
    read, and "when did it go out for delivery" should be a query, not a document scan.
    """

    __tablename__ = "order_status_history"
    __table_args__ = (Index("ix_order_status_history_order_at", "order_id", "changed_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    # Display name of whoever moved it; null when the system did (e.g. placement by a
    # customer, where `by` is the customer themselves and the app shows no actor).
    changed_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    changed_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrderNumberSequence(Base):
    """Concurrency-safe counter behind `ORD-2609-0151`.

    One row per merchant and month, incremented under `SELECT ... FOR UPDATE`, exactly as
    `customer_code_sequences` does for customer codes. A `MAX(order_number) + 1` scan would
    hand the same number to two simultaneous orders and the unique index would then reject
    one of them at random, losing a real order at the busiest moment.
    """

    __tablename__ = "order_number_sequences"

    # 'ORD-<merchant_id>-2609'. Composite rather than two columns because the lock is taken
    # on exactly one primary-key row.
    prefix: Mapped[str] = mapped_column(String(80), primary_key=True)
    next_value: Mapped[int] = mapped_column(BigInteger, default=1)
    # The month this counter belongs to, for the nightly cleanup of dead counters.
    period: Mapped[date] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
