"""Invoice and payment reads and writes (spec §12).

**The one rule this module exists to keep.** An invoice's `paidAmount` and `balance` are a
summary of the payments applied to it, and they are only ever written in the same transaction
as the payment that moves them. Nothing else touches them. Recording a payment, and later
marking one invalid, are the only two events that can change what a customer owes - so they are
the only two places those columns are assigned.

**Tenancy runs two ways here**, because both apps read the same rows. Merchant staff are scoped
to their merchant; a customer is scoped to their own profile. Neither can see the other's -
and, as everywhere on the platform, the answer to asking for somebody else's row is `404`
rather than `403`, because ids are guessable and a 403 confirms one exists.

**An invalid payment is not deleted.** Money that turned out never to have arrived is evidence:
somebody recorded a collection that was wrong, and who recorded it is the point. It stops
counting against the invoice, the balance comes back, and the row stays with a reason on it.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import status as http_status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.events import payments as payment_events
from app.modules.payments import validation
from app.modules.payments.constants import (
    ALL_STATUSES,
    SELF_EVIDENT_MODES,
    InvoiceStatus,
    PaymentMode,
    ReconciliationStatus,
)
from app.modules.payments.models import Invoice, Payment
from app.modules.payments.numbering import NumberAllocator
from app.modules.payments.schemas import (
    CustomerPaymentSummary,
    InvoiceResponse,
    PaymentResponse,
    ReconcilePaymentRequest,
    RecordPaymentRequest,
)
from app.shared.business.actor import BusinessActor
from app.shared.exceptions.api_error import ApiError
from app.shared.notifications.outbox import NotificationOutboxWriter


def _invoice_not_found() -> ApiError:
    return ApiError("INVOICE_NOT_FOUND", http_status.HTTP_404_NOT_FOUND)


def _payment_not_found() -> ApiError:
    return ApiError("PAYMENT_NOT_FOUND", http_status.HTTP_404_NOT_FOUND)


@dataclass
class InvoiceFilters:
    """Spec §12.2's query."""

    customer_id: str | None = None
    #: Only invoices with something still owed - the Record Payment picker's list.
    open_only: bool = False


@dataclass
class PaymentFilters:
    """Spec §12.3's query."""

    customer_id: str | None = None
    reconciliation_status: str | None = None
    #: Payment number, invoice number, customer name or bank reference.
    search: str | None = None


class PaymentService:
    def __init__(self, session: AsyncSession, actor: BusinessActor) -> None:
        self.session = session
        self.actor = actor
        self.notifications = NotificationOutboxWriter(session)

    # --- Reads ------------------------------------------------------------------------------

    async def list_invoices(self, filters: InvoiceFilters) -> list[InvoiceResponse]:
        """Invoices, newest issued first (spec §12.2)."""
        statement = self._scope_invoices(select(Invoice)).order_by(Invoice.issued_at.desc())
        if filters.customer_id:
            statement = statement.where(Invoice.customer_id == filters.customer_id)
        if filters.open_only:
            statement = statement.where(Invoice.balance > 0)
        now = datetime.now(UTC)
        return [_invoice_view(row, now=now) for row in await self.session.scalars(statement)]

    async def get_invoice(self, invoice_id: str) -> InvoiceResponse:
        return _invoice_view(await self._owned_invoice(invoice_id), now=datetime.now(UTC))

    async def list_payments(self, filters: PaymentFilters) -> list[PaymentResponse]:
        """Payments, newest collected first (spec §12.3).

        Ordered by `paidAt` rather than by when the row was written, because the two differ
        whenever a collection is typed in later - and the list is read as a record of when money
        arrived, not of when somebody got to their keyboard.
        """
        statement = self._scope_payments(select(Payment)).order_by(Payment.paid_at.desc())
        if filters.customer_id:
            statement = statement.where(Payment.customer_id == filters.customer_id)
        statement = self._apply_reconciliation(statement, filters.reconciliation_status)
        statement = self._apply_search(statement, filters.search)
        return [_payment_view(row) for row in await self.session.scalars(statement)]

    async def get_payment(self, payment_id: str) -> PaymentResponse:
        return _payment_view(await self._owned_payment(payment_id))

    async def summary(self, customer_id: str) -> CustomerPaymentSummary:
        """The header of the customer's Payments tab (spec §12.1).

        Summed from the invoices rather than kept as a running total on the customer, so it
        cannot drift: a stored balance is a second copy of a number the invoices already carry,
        and the two disagree the first time a write half-succeeds.
        """
        self._require_visible_customer(customer_id)
        now = datetime.now(UTC)

        totals = (
            await self.session.execute(
                select(
                    func.coalesce(func.sum(Invoice.total_amount), 0),
                    func.coalesce(func.sum(Invoice.paid_amount), 0),
                    func.coalesce(func.sum(Invoice.balance), 0),
                ).where(Invoice.customer_id == customer_id)
            )
        ).first() or (0, 0, 0)

        overdue = await self.session.scalar(
            select(func.coalesce(func.sum(Invoice.balance), 0)).where(
                Invoice.customer_id == customer_id,
                Invoice.balance > 0,
                Invoice.due_at < now,
            )
        )
        # INVALID payments are excluded: money that never arrived is not a last payment, and
        # showing it as one is how a customer is told they have paid when they have not.
        last_paid = await self.session.scalar(
            select(func.max(Payment.paid_at)).where(
                Payment.customer_id == customer_id,
                Payment.reconciliation_status != ReconciliationStatus.INVALID.value,
            )
        )
        return CustomerPaymentSummary(
            total_invoiced=int(totals[0] or 0),
            total_paid=int(totals[1] or 0),
            running_balance=int(totals[2] or 0),
            overdue_amount=int(overdue or 0),
            last_payment_at=last_paid,
        )

    # --- Recording a payment ----------------------------------------------------------------

    async def record(self, payload: RecordPaymentRequest) -> PaymentResponse:
        """Collect money against an open invoice (spec §12.5).

        Everything that can refuse runs first, then everything is written, then one commit. The
        invoice is locked for the duration: two people recording against the same invoice at the
        same time would otherwise both read the old balance and both be allowed, and the
        customer would end up having overpaid with no record of the credit.
        """
        invoice = validation.check_open(await self._locked_invoice(payload.invoice_id))
        now = datetime.now(UTC)
        amount = validation.check_amount(payload.amount, invoice)
        reference = validation.check_reference(payload.mode, payload.reference)
        paid_at = validation.check_paid_at(payload.paid_at, now=now)

        # Cash is settled the moment it is recorded - the person typing it in is holding the
        # notes. Anything else waits for somebody to find it in a bank statement.
        reconciliation = (
            ReconciliationStatus.RECONCILED
            if payload.mode in SELF_EVIDENT_MODES
            else ReconciliationStatus.PENDING
        )

        invoice_total = invoice.total_amount
        self._apply_to_invoice(invoice, delta=amount, now=now)
        # Read after the invoice is updated, so the receipt shows the balance as it stands once
        # this payment has landed - which is what the customer is looking at.
        running_balance = await self._running_balance(invoice.customer_id)

        number = await NumberAllocator(self.session, invoice.merchant_id).next_payment_number()
        payment = Payment(
            id=str(uuid4()),
            payment_number=number,
            merchant_id=invoice.merchant_id,
            invoice_id=invoice.id,
            invoice_number=invoice.invoice_number,
            customer_id=invoice.customer_id,
            customer_name=invoice.customer_name,
            invoice_amount=invoice_total,
            amount_collected=amount,
            mode=payload.mode.value,
            paid_at=paid_at,
            reference=reference,
            reconciliation_status=reconciliation.value,
            collected_by_user_id=self.actor.user_id,
            collected_by_name=self.actor.display_name,
            customer_running_balance=running_balance,
            note=(payload.note or "").strip() or None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(payment)
        self.notifications.queue(
            payment_events.payment_recorded(
                invoice.customer_id,
                payment.id,
                amount,
                payload.mode.value.title(),
                balance=running_balance,
            )
        )
        await self.session.commit()
        return _payment_view(payment)

    # --- Reconciliation ---------------------------------------------------------------------

    async def reconcile(
        self, payment_id: str, payload: ReconcilePaymentRequest
    ) -> PaymentResponse:
        """Settle a pending payment against the bank statement.

        **An addition.** §12 has no endpoint for it, but `ReconciliationStatus` has three values
        and the list filters on all three, so `PENDING` would be a state nothing could leave -
        and leaving it is the accountant's whole job on this screen.

        Marking a payment invalid puts its money back on the invoice. That is the consequential
        half: a customer who believes they have paid is told they still owe, so the reason is
        required and the row is kept rather than deleted.
        """
        payment = await self._owned_payment_row(payment_id)
        if payment.reconciliation_status != ReconciliationStatus.PENDING.value:
            raise ApiError(
                "PAYMENT_ALREADY_RECONCILED",
                http_status.HTTP_409_CONFLICT,
                f"Payment {payment.payment_number} is already "
                f"{payment.reconciliation_status.lower()}.",
            )
        reason = validation.check_reason(payload.reconciled, payload.reason)
        now = datetime.now(UTC)

        if payload.reconciled:
            payment.reconciliation_status = ReconciliationStatus.RECONCILED.value
            payment.invalid_reason = None
        else:
            payment.reconciliation_status = ReconciliationStatus.INVALID.value
            payment.invalid_reason = reason
            # The money never arrived, so the invoice is owed again.
            invoice = await self._locked_invoice(payment.invoice_id)
            self._apply_to_invoice(invoice, delta=-payment.amount_collected, now=now)
            # To staff, not the customer: an unreconciled payment may mean cylinders were
            # released against money that never arrived, and that is the office's problem to
            # chase before it is the customer's.
            self.notifications.queue(
                payment_events.payment_invalid(
                    payment.merchant_id, payment.id, payment.amount_collected, reason or ""
                )
            )

        payment.reconciled_at = now
        payment.reconciled_by_name = self.actor.display_name
        payment.updated_at = now
        await self.session.commit()
        return _payment_view(payment)

    # --- The only place invoice money is written --------------------------------------------

    @staticmethod
    def _apply_to_invoice(invoice: Invoice, *, delta: int, now: datetime) -> None:
        """Move money onto or off an invoice, and re-derive its status.

        `status` is never assigned from outside: it is a reading of the balance, and the two
        going out of step is how an invoice ends up marked PAID while still owing something.
        """
        invoice.paid_amount = max(invoice.paid_amount + delta, 0)
        invoice.balance = max(invoice.total_amount - invoice.paid_amount, 0)
        if invoice.balance <= 0:
            invoice.status = InvoiceStatus.PAID.value
        elif invoice.paid_amount > 0:
            invoice.status = InvoiceStatus.PARTIAL.value
        else:
            invoice.status = InvoiceStatus.UNPAID.value
        invoice.updated_at = now

    async def _running_balance(self, customer_id: str) -> int:
        """What this customer still owes across every open invoice."""
        total = await self.session.scalar(
            select(func.coalesce(func.sum(Invoice.balance), 0)).where(
                Invoice.customer_id == customer_id
            )
        )
        return int(total or 0)

    # --- Scope and lookups ------------------------------------------------------------------

    def _scope_invoices(self, statement: Select) -> Select:
        """Merchant staff see their merchant's invoices; a customer sees their own."""
        if self.actor.is_customer:
            return statement.where(Invoice.customer_id == self.actor.require_customer_id())
        return statement.where(Invoice.merchant_id == self.actor.require_merchant_id())

    def _scope_payments(self, statement: Select) -> Select:
        if self.actor.is_customer:
            return statement.where(Payment.customer_id == self.actor.require_customer_id())
        return statement.where(Payment.merchant_id == self.actor.require_merchant_id())

    def _require_visible_customer(self, customer_id: str) -> None:
        """A customer may only ask for their own summary."""
        if self.actor.is_customer and customer_id != self.actor.require_customer_id():
            raise ApiError("CUSTOMER_NOT_FOUND", http_status.HTTP_404_NOT_FOUND)

    async def _owned_invoice(self, invoice_id: str) -> Invoice:
        invoice = await self.session.scalar(
            self._scope_invoices(select(Invoice)).where(Invoice.id == invoice_id)
        )
        if invoice is None:
            raise _invoice_not_found()
        return invoice

    async def _locked_invoice(self, invoice_id: str) -> Invoice:
        """The invoice, locked for this transaction.

        `FOR UPDATE` rather than a plain read: the balance is about to be changed based on what
        it is now, and two concurrent collections reading the same old balance would both be
        allowed through a check that should have refused the second.
        """
        invoice = await self.session.scalar(
            self._scope_invoices(select(Invoice)).where(Invoice.id == invoice_id).with_for_update()
        )
        if invoice is None:
            raise _invoice_not_found()
        return invoice

    async def _owned_payment_row(self, payment_id: str) -> Payment:
        payment = await self.session.scalar(
            self._scope_payments(select(Payment)).where(Payment.id == payment_id)
        )
        if payment is None:
            raise _payment_not_found()
        return payment

    async def _owned_payment(self, payment_id: str) -> Payment:
        return await self._owned_payment_row(payment_id)

    @staticmethod
    def _apply_reconciliation(statement: Select, value: str | None) -> Select:
        if not value or value.upper() == ALL_STATUSES:
            return statement
        try:
            wanted = ReconciliationStatus(value.upper())
        except ValueError:
            raise validation.invalid(
                "reconciliationStatus",
                "unknown_status",
                "Filter by PENDING, RECONCILED, INVALID or ALL.",
            ) from None
        return statement.where(Payment.reconciliation_status == wanted.value)

    @staticmethod
    def _apply_search(statement: Select, value: str | None) -> Select:
        term = (value or "").strip()
        if not term:
            return statement
        like = f"%{term}%"
        return statement.where(
            or_(
                Payment.payment_number.like(like),
                Payment.invoice_number.like(like),
                Payment.customer_name.like(like),
                Payment.reference.like(like),
            )
        )


def _invoice_view(invoice: Invoice, *, now: datetime) -> InvoiceResponse:
    due = invoice.due_at if invoice.due_at.tzinfo else invoice.due_at.replace(tzinfo=UTC)
    return InvoiceResponse(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        order_id=invoice.order_id,
        order_number=invoice.order_number,
        customer_id=invoice.customer_id,
        customer_name=invoice.customer_name,
        amount=invoice.amount,
        gst_percent=invoice.gst_percent,
        gst_amount=invoice.gst_amount,
        total_amount=invoice.total_amount,
        paid_amount=invoice.paid_amount,
        balance=invoice.balance,
        status=InvoiceStatus(invoice.status),
        issued_at=invoice.issued_at,
        due_at=invoice.due_at,
        # Computed on the way out rather than stored: an overdue flag in the table is wrong from
        # the moment the clock passes midnight until something writes to the row again.
        is_overdue=invoice.balance > 0 and due < now,
        is_gst_invoice=invoice.is_gst_invoice,
        gstin=invoice.gstin,
    )


def _payment_view(payment: Payment) -> PaymentResponse:
    return PaymentResponse(
        id=payment.id,
        payment_number=payment.payment_number,
        invoice_id=payment.invoice_id,
        invoice_number=payment.invoice_number,
        customer_id=payment.customer_id,
        customer_name=payment.customer_name,
        invoice_amount=payment.invoice_amount,
        amount_collected=payment.amount_collected,
        mode=PaymentMode(payment.mode),
        paid_at=payment.paid_at,
        reference=payment.reference,
        reconciliation_status=ReconciliationStatus(payment.reconciliation_status),
        invalid_reason=payment.invalid_reason,
        collected_by=payment.collected_by_name,
        customer_running_balance=payment.customer_running_balance,
        note=payment.note,
    )
