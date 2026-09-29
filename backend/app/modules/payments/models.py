"""Invoice and payment tables (spec §3.14, §3.15, §12).

An invoice **copies** what the order said when it was raised - customer name, amounts, the GST
split - for the same reason a delivery slip copies its address: an invoice is a legal document
about a moment in time, and it has to keep saying what was billed after the customer is renamed
or the order's prices are examined in a dispute.

`paid_amount` and `balance` are stored rather than summed on every read, because they are what
the list screens sort and filter on and a subquery per row is how that screen gets slow. They
are only ever written by `PaymentService`, in the same transaction as the payment that moved
them, so the pair cannot drift from the payment rows behind it.

Three tables:

* `invoices` - what a customer owes, one per delivered order.
* `payments` - each act of collecting. Several may land on one invoice.
* `payment_number_sequences` - the per-merchant counters behind `MBGA/INV/0144` and `PAY-0211`.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base

#: Ordering carries meaning on both tables - "newest payment first", "last payment at" - and
#: MySQL DATETIME without a fractional part keeps only whole seconds, so two payments recorded
#: in the same second come back in arbitrary order. Used wherever a sort depends on it.
_MICROS = DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("merchant_id", "invoice_number", name="uq_invoices_merchant_number"),
        # One invoice per order. The constraint is the guard, not a check in the service: a
        # retried delivery confirmation must not be able to bill a customer twice.
        UniqueConstraint("order_id", name="uq_invoices_order"),
        # The customer's Payments tab: their invoices, newest first, open ones filtered.
        Index("ix_invoices_customer_issued", "customer_id", "issued_at"),
        # "What is still owed to this merchant" - the dashboard KPI and the open-invoice picker.
        Index("ix_invoices_merchant_status", "merchant_id", "status"),
        # Overdue: open invoices past their due date.
        Index("ix_invoices_merchant_due", "merchant_id", "due_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    #: `MBGA/INV/0144`. Printed on the document and quoted by the customer, so it is readable
    #: and sequential per merchant. Never used for authorisation - it is guessable by design.
    invoice_number: Mapped[str] = mapped_column(String(40), index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)

    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    order_number: Mapped[str] = mapped_column(String(30))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"), index=True)
    #: Copied. The invoice must keep naming who was billed even after the profile is edited.
    customer_name: Mapped[str] = mapped_column(String(160))

    #: Taxable value. `gst_amount` is broken **out of** `total_amount`, never added on top.
    amount: Mapped[int] = mapped_column(BigInteger)
    gst_percent: Mapped[int] = mapped_column(Integer)
    gst_amount: Mapped[int] = mapped_column(BigInteger)
    total_amount: Mapped[int] = mapped_column(BigInteger)

    #: Sum of this invoice's non-INVALID payments, and what is left. Written only alongside the
    #: payment that changes them, so they cannot disagree with the rows behind them.
    paid_amount: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    balance: Mapped[int] = mapped_column(BigInteger)
    #: Derived from the balance. Stored because the list filters on it.
    status: Mapped[str] = mapped_column(String(20), index=True)

    issued_at: Mapped[datetime] = mapped_column(_MICROS)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    #: True for a customer who needs a tax invoice - an industrial buyer claiming input credit.
    #: The GST split is present either way; this decides which document is printed.
    is_gst_invoice: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    #: The customer's GSTIN as it stood when the invoice was raised. Copied, like the name.
    gstin: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Payment(Base):
    """One act of collecting money against one invoice."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("merchant_id", "payment_number", name="uq_payments_merchant_number"),
        # The payments list: this merchant's, newest first, filtered by reconciliation state.
        Index("ix_payments_merchant_paid_at", "merchant_id", "paid_at"),
        Index("ix_payments_merchant_reconciliation", "merchant_id", "reconciliation_status"),
        # A customer's payment history, and the invoice detail's list of what was applied to it.
        Index("ix_payments_customer_paid_at", "customer_id", "paid_at"),
        Index("ix_payments_invoice", "invoice_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    #: `PAY-0211`. Quoted on a receipt.
    payment_number: Mapped[str] = mapped_column(String(30), index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)

    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id"), index=True)
    #: Copied so the list renders without joining invoices.
    invoice_number: Mapped[str] = mapped_column(String(40))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"), index=True)
    customer_name: Mapped[str] = mapped_column(String(160))

    #: The invoice's total when this payment was taken. Copied because a receipt has to show
    #: what the bill was, and the invoice's own figures are about the invoice's whole life.
    invoice_amount: Mapped[int] = mapped_column(BigInteger)
    amount_collected: Mapped[int] = mapped_column(BigInteger)
    mode: Mapped[str] = mapped_column(String(10))

    #: When the money actually changed hands - which is not when it was typed in. A driver
    #: collects cash at 11:00 and the office records it at 18:00; the report follows this one.
    paid_at: Mapped[datetime] = mapped_column(_MICROS, index=True)
    #: UTR, UPI transaction id, cheque number. Required for anything but cash, because without
    #: it the payment can never be matched against a bank statement.
    reference: Mapped[str | None] = mapped_column(String(80), nullable=True)

    reconciliation_status: Mapped[str] = mapped_column(String(20), index=True)
    #: Why the bank match failed. Free text: it is read by a person deciding what to do next.
    invalid_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciled_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)

    #: Who took the money. Resolved from the session, never from the body.
    collected_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    collected_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)

    #: What the customer still owed across all their open invoices immediately after this
    #: payment. Stored rather than recomputed, because a receipt printed today has to keep
    #: showing the balance it showed today, even after next week's invoice is raised.
    customer_running_balance: Mapped[int] = mapped_column(BigInteger)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaymentNumberSequence(Base):
    """Concurrency-safe counters behind `MBGA/INV/0144` and `PAY-0211`.

    One row per merchant per kind, incremented under `SELECT ... FOR UPDATE`, exactly as
    `orders/numbering.py` and `deliveries/numbering.py` already do. Neither counter resets: an
    invoice run that restarts every month would produce two `MBGA/INV/0001` in one financial
    year, which is the one thing an invoice number must never do.
    """

    __tablename__ = "payment_number_sequences"

    prefix: Mapped[str] = mapped_column(String(120), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
