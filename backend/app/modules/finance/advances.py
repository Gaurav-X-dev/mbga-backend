from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.modules.customers.models import CustomerProfile
from app.modules.finance.models import (
    AdvanceAccount,
    AdvanceDeposit,
    AdvanceEntry,
    AdvanceReservation,
)
from app.modules.finance.settings import audit, policy
from app.modules.payments.models import Invoice, Payment
from app.modules.payments.numbering import NumberAllocator
from app.shared.exceptions.api_error import ApiError
from app.shared.notifications.outbox import NotificationEvent, NotificationOutboxWriter


async def account(session, customer_id, merchant_id, *, create=False):
    # Current reads after the customer lock serialize first account creation without a race.
    row = await session.scalar(
        select(AdvanceAccount)
        .where(AdvanceAccount.customer_id == customer_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None and create:
        await session.scalar(
            select(CustomerProfile)
            .where(CustomerProfile.id == customer_id, CustomerProfile.merchant_id == merchant_id)
            .with_for_update()
        )
        row = await session.scalar(
            select(AdvanceAccount)
            .where(AdvanceAccount.customer_id == customer_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            row = AdvanceAccount(
                customer_id=customer_id,
                merchant_id=merchant_id,
                balance=0,
                reserved=0,
                updated_at=datetime.now(UTC),
            )
            session.add(row)
            await session.flush()
    if row and row.merchant_id != merchant_id:
        raise ApiError("CUSTOMER_NOT_FOUND", 404)
    return row


async def summary(session, customer_id, merchant_id):
    row = await session.get(AdvanceAccount, customer_id)
    if row and row.merchant_id != merchant_id:
        raise ApiError("CUSTOMER_NOT_FOUND", 404)
    settings = await policy(session, merchant_id)
    balance = int(row.balance) if row else 0
    held = int(row.reserved) if row else 0
    return {
        "customerId": customer_id,
        "merchantId": merchant_id,
        "balance": balance,
        "reserved": held,
        "available": balance - held,
        "enabled": settings.advanceEnabled,
        "autoUseAdvance": settings.autoUseAdvance,
        "allocationPolicy": "FUTURE_ORDERS_ONLY",
        "maxDepositAmount": settings.maxDepositAmount,
    }


def entry(
    session,
    row,
    kind,
    amount,
    key,
    actor_id,
    *,
    payment_id=None,
    order_id=None,
    reference=None,
    notes=None,
):
    row.balance += amount
    row.updated_at = datetime.now(UTC)
    if row.balance < row.reserved or row.reserved < 0:
        raise ApiError(
            "ADVANCE_BALANCE_CHANGED",
            409,
            "Available advance is insufficient or reserved by another order.",
        )
    result = AdvanceEntry(
        id=str(uuid4()),
        merchant_id=row.merchant_id,
        customer_id=row.customer_id,
        kind=kind,
        amount=amount,
        balance_after=row.balance,
        idempotency_key=key,
        actor_id=actor_id,
        created_at=row.updated_at,
        payment_id=payment_id,
        order_id=order_id,
        reference=reference,
        notes=notes,
    )
    session.add(result)
    return result


async def request_deposit(session, actor, payload, customer):
    if customer.status != "APPROVED":
        raise ApiError("CUSTOMER_NOT_APPROVED", 409, "Advances require an approved customer.")
    settings = await policy(session, customer.merchant_id)
    if not settings.advanceEnabled:
        raise ApiError("ADVANCE_DISABLED", 403, "Customer advances are disabled for this merchant.")
    if payload.amount > settings.maxDepositAmount:
        raise ApiError("ADVANCE_LIMIT", 422, "Deposit exceeds the configured limit.")
    if actor.is_customer and payload.mode == "CASH":
        raise ApiError(
            "ADVANCE_CASH_OFFICE_ONLY", 403, "Cash advances must be recorded at the office."
        )
    await session.scalar(
        select(CustomerProfile).where(CustomerProfile.id == customer.id).with_for_update()
    )
    existing = await session.scalar(
        select(AdvanceDeposit)
        .where(
            AdvanceDeposit.merchant_id == customer.merchant_id,
            AdvanceDeposit.idempotency_key == payload.idempotencyKey,
        )
        .with_for_update()
    )
    reference = (payload.reference or "").strip().upper() or None
    if existing:
        if (
            existing.customer_id,
            existing.amount,
            existing.mode,
            existing.reference,
            existing.notes,
            existing.created_by,
        ) != (customer.id, payload.amount, payload.mode, reference, payload.notes, actor.user_id):
            raise ApiError(
                "IDEMPOTENCY_CONFLICT", 409, "This deposit key was used for different data."
            )
        return existing
    if reference and await session.scalar(
        select(AdvanceDeposit.id)
        .where(
            AdvanceDeposit.merchant_id == customer.merchant_id,
            AdvanceDeposit.reference == reference,
        )
        .limit(1)
    ):
        raise ApiError(
            "DEPOSIT_REFERENCE_USED", 409, "This transaction reference was already submitted."
        )
    row = AdvanceDeposit(
        id=str(uuid4()),
        merchant_id=customer.merchant_id,
        customer_id=customer.id,
        amount=payload.amount,
        mode=payload.mode,
        reference=reference,
        idempotency_key=payload.idempotencyKey,
        status="PENDING",
        created_by=actor.user_id,
        notes=payload.notes,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    audit(
        session,
        actor.user_id,
        row.id,
        f"Advance deposit submitted; customer {customer.id}; amount {row.amount}; verification pending",
    )
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(
            "DEPOSIT_REFERENCE_USED",
            409,
            "This payment reference or request key is already registered.",
        ) from exc
    return row


async def verify_deposit(session, actor, deposit_id, verified, reason):
    # Deposit decisions are serialized on the customer, then deposit, then advance account.
    initial = await session.scalar(
        select(AdvanceDeposit).where(
            AdvanceDeposit.id == deposit_id, AdvanceDeposit.merchant_id == actor.merchant_id
        )
    )
    if initial is None:
        raise ApiError("DEPOSIT_NOT_FOUND", 404)
    await session.scalar(
        select(CustomerProfile).where(CustomerProfile.id == initial.customer_id).with_for_update()
    )
    deposit = await session.scalar(
        select(AdvanceDeposit)
        .where(AdvanceDeposit.id == deposit_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    wanted = "VERIFIED" if verified else "REJECTED"
    if deposit.status != "PENDING":
        if deposit.status == wanted:
            return deposit
        raise ApiError("DEPOSIT_DECIDED", 409, "This deposit has already been decided.")
    settings = await policy(session, actor.merchant_id)
    if verified and not settings.advanceEnabled:
        raise ApiError("ADVANCE_DISABLED", 403)
    if settings.requireSeparateVerifier and deposit.created_by == actor.user_id:
        raise ApiError(
            "SEPARATE_VERIFIER_REQUIRED",
            403,
            "A different authorized user must verify this receipt.",
        )
    if verified:
        row = await account(session, deposit.customer_id, deposit.merchant_id, create=True)
        entry(
            session,
            row,
            "DEPOSIT",
            deposit.amount,
            "deposit:" + deposit.id,
            actor.user_id,
            reference=deposit.reference,
            notes=reason,
        )
        NotificationOutboxWriter(session).queue(
            NotificationEvent(
                event_type="advance.deposit_verified",
                recipient_kind="customer",
                recipient_id=deposit.customer_id,
                entity_type="advance",
                entity_id=deposit.id,
                title="Advance received",
                body=f"Your advance payment of ₹{deposit.amount} is verified. Available advance: ₹{row.balance - row.reserved}.",
            )
        )
    deposit.status, deposit.verified_by, deposit.verified_at = (
        wanted,
        actor.user_id,
        datetime.now(UTC),
    )
    audit(
        session, actor.user_id, deposit.id, f"Advance {wanted}; amount {deposit.amount}; {reason}"
    )
    await session.flush()
    return deposit


async def refund(session, actor, payload):
    payload.reference = payload.reference.upper()
    row = await account(session, payload.customerId, actor.merchant_id)
    if row is None:
        raise ApiError("ADVANCE_INSUFFICIENT", 409, "No advance is available.")
    existing = await session.scalar(
        select(AdvanceEntry)
        .where(
            AdvanceEntry.merchant_id == actor.merchant_id,
            AdvanceEntry.idempotency_key == "refund:" + payload.idempotencyKey,
        )
        .with_for_update()
    )
    if existing:
        if (existing.customer_id, existing.amount, existing.reference, existing.notes) != (
            payload.customerId,
            -payload.amount,
            payload.reference,
            payload.reason,
        ):
            raise ApiError("IDEMPOTENCY_CONFLICT", 409)
        return existing
    if row.balance - row.reserved < payload.amount:
        raise ApiError("ADVANCE_INSUFFICIENT", 409, "Reserved funds cannot be refunded.")
    if await session.scalar(
        select(AdvanceEntry.id)
        .where(
            AdvanceEntry.merchant_id == actor.merchant_id,
            AdvanceEntry.kind == "REFUND",
            AdvanceEntry.reference == payload.reference,
        )
        .limit(1)
    ):
        raise ApiError("REFUND_REFERENCE_USED", 409)
    result = entry(
        session,
        row,
        "REFUND",
        -payload.amount,
        "refund:" + payload.idempotencyKey,
        actor.user_id,
        reference=payload.reference,
        notes=payload.reason,
    )
    audit(
        session,
        actor.user_id,
        result.id,
        f"Advance refund recorded; customer {row.customer_id}; amount {payload.amount}; {payload.reason}",
    )
    return result


async def credit_adjustment(session, customer, pending_orders, proposed_amount):
    """Called only after existing invoice/order locks; never acquires those locks backwards."""
    settings = await policy(session, customer.merchant_id)
    held = 0
    if pending_orders:
        reservations = (
            await session.scalars(
                select(AdvanceReservation)
                .where(
                    AdvanceReservation.order_id.in_(pending_orders),
                    AdvanceReservation.status == "HELD",
                )
                .with_for_update()
            )
        ).all()
        held = sum(int(r.amount) for r in reservations)
    row = await account(session, customer.id, customer.merchant_id)
    available = (
        (row.balance - row.reserved)
        if row and settings.advanceEnabled and settings.autoUseAdvance
        else 0
    )
    usable = min(available, proposed_amount)
    if not settings.allowPartialAdvance and usable < proposed_amount:
        usable = 0
    return held, usable


async def reserve(session, order, actor_id):
    settings = await policy(session, order.merchant_id)
    if not settings.advanceEnabled or not settings.autoUseAdvance:
        return 0
    existing = await session.get(AdvanceReservation, order.id)
    if existing:
        return existing.amount if existing.status == "HELD" else 0
    row = await account(session, order.customer_id, order.merchant_id)
    if row is None:
        return 0
    amount = min(row.balance - row.reserved, order.total_amount)
    if not settings.allowPartialAdvance and amount < order.total_amount:
        amount = 0
    if amount <= 0:
        return 0
    row.reserved += amount
    row.updated_at = datetime.now(UTC)
    session.add(
        AdvanceReservation(
            order_id=order.id,
            customer_id=order.customer_id,
            merchant_id=order.merchant_id,
            amount=amount,
            applied_amount=0,
            status="HELD",
            created_at=row.updated_at,
            updated_at=row.updated_at,
        )
    )
    audit(session, actor_id, order.id, f"Advance reserved: {amount}")
    await session.flush()
    return amount


async def release(session, order_id):
    hold = await session.scalar(
        select(AdvanceReservation).where(AdvanceReservation.order_id == order_id).with_for_update()
    )
    if hold is None or hold.status != "HELD":
        return
    row = await account(session, hold.customer_id, hold.merchant_id)
    row.reserved -= hold.amount
    hold.status, hold.updated_at = "RELEASED", datetime.now(UTC)
    audit(session, None, order_id, f"Advance released: {hold.amount}")
    await session.flush()


async def apply_to_invoice(session, order, invoice):
    hold = await session.scalar(
        select(AdvanceReservation).where(AdvanceReservation.order_id == order.id).with_for_update()
    )
    if hold is None or hold.status != "HELD":
        return
    row = await account(session, hold.customer_id, hold.merchant_id)
    amount = min(hold.amount, invoice.balance)
    row.reserved -= hold.amount
    hold.applied_amount, hold.status, hold.updated_at = amount, "APPLIED", datetime.now(UTC)
    if amount:
        from app.modules.payments.service import PaymentService

        PaymentService._apply_to_invoice(invoice, delta=amount, now=hold.updated_at)
        payment = Payment(
            id=str(uuid4()),
            payment_number=await NumberAllocator(session, order.merchant_id).next_payment_number(),
            merchant_id=order.merchant_id,
            invoice_id=invoice.id,
            invoice_number=invoice.invoice_number,
            customer_id=order.customer_id,
            customer_name=invoice.customer_name,
            invoice_amount=invoice.total_amount,
            amount_collected=amount,
            applied_amount=amount,
            mode="ADVANCE",
            cash_amount=0,
            upi_amount=0,
            paid_at=hold.updated_at,
            reconciliation_status="RECONCILED",
            collected_by_name="Advance adjustment",
            customer_running_balance=0,
            note="Reserved customer advance applied to invoice",
            created_at=hold.updated_at,
            updated_at=hold.updated_at,
        )
        session.add(payment)
        await session.flush()
        payment.customer_running_balance = int(
            await session.scalar(
                select(func.coalesce(func.sum(Invoice.balance), 0)).where(
                    Invoice.customer_id == order.customer_id,
                    Invoice.merchant_id == order.merchant_id,
                )
            )
            or 0
        )
        entry(
            session,
            row,
            "APPLY",
            -amount,
            "invoice:" + invoice.id,
            "system",
            payment_id=payment.id,
            order_id=order.id,
            reference=invoice.invoice_number,
        )
    await session.flush()


async def held_amount(session, order_id):
    hold = await session.scalar(
        select(AdvanceReservation).where(AdvanceReservation.order_id == order_id)
    )
    return int(hold.amount) if hold and hold.status == "HELD" else 0
