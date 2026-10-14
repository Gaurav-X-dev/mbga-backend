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
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
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
    # Copied from the delivery site at creation, like the address above and for the same reason:
    # a slip has to keep saying where the van was sent even after the site is edited. Null for
    # most slips - an order usually goes to the customer's registered address, which nobody has
    # surveyed - and every read treats null as "cannot measure", never as "wrong place".
    destination_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    destination_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

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
    # When the driver pressed Start on their phone, and where they were. Separate from
    # `dispatched_at`, which is the office marking the van loaded: the two are often an hour
    # apart, and only this one is evidence of where the driver actually was.
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    driver_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    driver_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 0 until the delivery is confirmed (spec §3.12). `pendingPickup` is derived from this and
    # `cylinders_allocated` rather than stored, so the two can never disagree.
    empties_collected: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    confirmation_method: Mapped[str] = mapped_column(String(20))
    # The proof-of-delivery code, hashed. Never stored in the clear: it is read out at a gate,
    # and a plain column would be a shared secret sitting in the table that the whole office
    # can query. Null when the method is NONE, or once the slip is confirmed and it is spent.
    confirmation_code_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Reversible copy for the owning customer's order screen. It is encrypted with a
    # purpose-specific key, is never returned to merchant/delivery APIs, and is erased when the
    # slip reaches DELIVERED or FAILED. The hash above remains the verification source.
    confirmation_code_encrypted: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confirmation_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # What the driver says he collected at the gate, written when he confirms his counts and
    # acted on when the customer's code completes the handover. It is stated in one request and
    # banked in another - the invoice it pays does not exist until the second - so it is parked
    # here rather than carried between them, the same way `delivered_quantity` is.
    #
    # Null means no money was taken: the customer is paying later, or the office confirmed the
    # slip itself. That is an ordinary outcome, not a missing value.
    payment_mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Whole rupees, as everywhere else on the platform.
    payment_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # The UTR or UPI transaction id. Required for anything but cash, because without it the
    # payment can never be matched against a bank statement.
    payment_reference: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # The last UPI QR shown at this gate, and when. Nothing was recorded before: the endpoint
    # built a link, returned it and forgot it, so "a QR for 3,380 was shown at 14:32" was a
    # thing nobody could find out. It is the only trace the platform has of a UPI collection
    # being asked for, because no gateway tells it whether the money arrived.
    qr_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    qr_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Evidence captured by the delivery app for a UPI collection. The public URL is an
    # authenticated API URL; the opaque storage key is never returned to a client.
    payment_proof_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payment_proof_storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_proof_content_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payment_proof_captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payment_proof_uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    status: Mapped[str] = mapped_column(String(20), index=True)
    # Why a slip failed. The cancelled order is final, but staff still need the reason for the
    # customer conversation and for deciding whether to accept a fresh order.
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
    # What the driver actually handed over, recorded at the gate. `None` means nothing was
    # recorded - the office confirmed the slip itself, or it predates the driver app - and the
    # ledger then books the whole allocation. Kept separate from `quantity` because the
    # allocation is what the van stays answerable for while it is out.
    delivered_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # How many empties of this size came back. Kept per type for the same reason
    # `delivered_quantity` is: the slip's own `empties_collected` is one number across every
    # size, which is enough for the ledger but tells the driver's receipt and the godown
    # nothing about which cylinders actually returned. Without it the receipt listed the
    # delivered lines in the empties column, so a handover of 2 and 1 printed "Total: 2" over
    # rows adding to 3.
    #
    # `None` means nothing was recorded per type - an older slip, or one the office confirmed.
    empties_collected: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
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
