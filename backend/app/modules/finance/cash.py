"""Track physical cash movement; never mutate customer invoices or payment amounts."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.modules.deliveries.models import DeliverySlip
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.finance.models import CashCustody, CashHandover, CashHandoverItem
from app.modules.finance.settings import audit, policy
from app.shared.exceptions.api_error import ApiError


async def capture(session, payment):
    """New driver cash only. Historical cash is not presumed to still be with the driver."""
    driver = await session.scalar(
        select(DeliveryProfile)
        .where(
            DeliveryProfile.merchant_id == payment.merchant_id,
            DeliveryProfile.user_id == payment.collected_by_user_id,
        )
        .order_by(DeliveryProfile.id)
        .limit(1)
    )
    if driver is None:
        return
    slip = await session.get(DeliverySlip, payment.delivery_id)
    if slip is None or slip.merchant_id != payment.merchant_id:
        raise ApiError("DELIVERY_NOT_FOUND", 404)
    await session.flush()
    session.add(
        CashCustody(
            payment_id=payment.id,
            merchant_id=payment.merchant_id,
            driver_id=driver.id,
            driver_user_id=driver.user_id,
            driver_name=payment.collected_by_name or "Driver",
            vehicle_number=slip.vehicle_number,
            invoice_number=payment.invoice_number,
            cash_amount=payment.cash_amount,
            received_amount=0,
            collected_at=payment.paid_at,
        )
    )


async def driver_lock(session, merchant_id, driver_id):
    row = await session.scalar(
        select(DeliveryProfile)
        .where(DeliveryProfile.id == driver_id, DeliveryProfile.merchant_id == merchant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise ApiError("DRIVER_NOT_FOUND", 404)
    return row


async def pending_claims(session, payment_ids):
    if not payment_ids:
        return {}
    pairs = (
        await session.execute(
            select(CashHandoverItem.payment_id, CashHandoverItem.expected_amount)
            .join(CashHandover, CashHandover.id == CashHandoverItem.handover_id)
            .where(CashHandoverItem.payment_id.in_(payment_ids), CashHandover.status == "SUBMITTED")
            .with_for_update()
        )
    ).all()
    totals = {}
    for payment_id, amount in pairs:
        totals[payment_id] = totals.get(payment_id, 0) + amount
    return totals


async def submit(session, actor, payload, driver_id):
    settings = await policy(session, actor.merchant_id)
    if not settings.handoverEnabled:
        raise ApiError("HANDOVER_DISABLED", 403)
    await driver_lock(session, actor.merchant_id, driver_id)
    ids = sorted(set(payload.paymentIds))
    if len(ids) != len(payload.paymentIds):
        raise ApiError("DUPLICATE_COLLECTION", 422, "Select each collection once.")
    existing = await session.scalar(
        select(CashHandover)
        .where(
            CashHandover.merchant_id == actor.merchant_id,
            CashHandover.idempotency_key == payload.idempotencyKey,
        )
        .with_for_update()
    )
    if existing:
        old = sorted(
            (
                await session.scalars(
                    select(CashHandoverItem.payment_id).where(
                        CashHandoverItem.handover_id == existing.id
                    )
                )
            ).all()
        )
        if (
            old != ids
            or existing.driver_id != driver_id
            or existing.created_by != actor.user_id
            or existing.notes != payload.notes
        ):
            raise ApiError("IDEMPOTENCY_CONFLICT", 409)
        return existing
    records = (
        await session.scalars(
            select(CashCustody)
            .where(
                CashCustody.payment_id.in_(ids),
                CashCustody.driver_id == driver_id,
                CashCustody.merchant_id == actor.merchant_id,
            )
            .order_by(CashCustody.payment_id)
            .with_for_update()
        )
    ).all()
    if len(records) != len(ids):
        raise ApiError(
            "COLLECTION_NOT_FOUND",
            404,
            "Every selection must belong to the selected driver and merchant.",
        )
    claims = await pending_claims(session, ids)
    if any(
        claims.get(row.payment_id, 0) or row.cash_amount <= row.received_amount for row in records
    ):
        raise ApiError(
            "COLLECTION_ALREADY_CLAIMED",
            409,
            "A selected collection is already submitted or fully handed over. Refresh the list.",
        )
    now = datetime.now(UTC)
    batch = CashHandover(
        id=str(uuid4()),
        merchant_id=actor.merchant_id,
        driver_id=driver_id,
        idempotency_key=payload.idempotencyKey,
        expected_amount=sum(r.cash_amount - r.received_amount for r in records),
        status="SUBMITTED",
        notes=payload.notes,
        created_by=actor.user_id,
        created_at=now,
    )
    session.add(batch)
    await session.flush()
    for row in records:
        session.add(
            CashHandoverItem(
                id=str(uuid4()),
                handover_id=batch.id,
                payment_id=row.payment_id,
                expected_amount=row.cash_amount - row.received_amount,
                received_amount=0,
            )
        )
    audit(
        session,
        actor.user_id,
        batch.id,
        f"Cash handover submitted; driver {driver_id}; expected {batch.expected_amount}",
    )
    await session.flush()
    return batch


async def verify(session, actor, batch_id, payload):
    initial = await session.scalar(
        select(CashHandover).where(
            CashHandover.id == batch_id, CashHandover.merchant_id == actor.merchant_id
        )
    )
    if initial is None:
        raise ApiError("HANDOVER_NOT_FOUND", 404)
    driver = await driver_lock(session, actor.merchant_id, initial.driver_id)
    batch = await session.scalar(
        select(CashHandover)
        .where(CashHandover.id == batch_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if batch.status != "SUBMITTED":
        wanted = (
            "REJECTED"
            if payload.reject
            else "VERIFIED"
            if payload.receivedAmount == batch.expected_amount
            else "VERIFIED_WITH_DIFFERENCE"
        )
        if batch.status == wanted and (
            payload.reject or batch.received_amount == payload.receivedAmount
        ):
            return batch
        raise ApiError("HANDOVER_DECIDED", 409, "This handover has already been decided.")
    settings = await policy(session, actor.merchant_id)
    if actor.user_id == driver.user_id:
        raise ApiError(
            "SEPARATE_VERIFIER_REQUIRED",
            403,
            "You are signed in as the driver who collected this cash. Another authorized office user must verify or reject this handover.",
        )
    if settings.requireSeparateVerifier and actor.user_id == batch.created_by:
        raise ApiError(
            "SEPARATE_VERIFIER_REQUIRED",
            403,
            "Separate office verification is enabled. A different authorized office user must verify or reject this handover.",
        )
    if payload.reject and payload.receivedAmount != 0:
        raise ApiError(
            "INVALID_CASH_RECEIPT", 422, "A rejected handover must not record received cash."
        )
    now = datetime.now(UTC)
    batch.status = (
        "REJECTED"
        if payload.reject
        else "VERIFIED"
        if payload.receivedAmount == batch.expected_amount
        else "VERIFIED_WITH_DIFFERENCE"
    )
    batch.received_amount = 0 if payload.reject else payload.receivedAmount
    batch.difference = batch.received_amount - batch.expected_amount
    batch.verification_notes = payload.notes
    batch.verified_by, batch.verified_at = actor.user_id, now
    if not payload.reject:
        pairs = (
            await session.execute(
                select(CashHandoverItem, CashCustody)
                .join(CashCustody, CashCustody.payment_id == CashHandoverItem.payment_id)
                .where(CashHandoverItem.handover_id == batch.id)
                .order_by(CashCustody.collected_at, CashCustody.payment_id)
                .with_for_update()
            )
        ).all()
        remaining = min(batch.received_amount, batch.expected_amount)
        for item, custody in pairs:
            available = custody.cash_amount - custody.received_amount
            if available < item.expected_amount:
                raise ApiError("CASH_BALANCE_CHANGED", 409)
            item.received_amount = min(item.expected_amount, remaining)
            custody.received_amount += item.received_amount
            remaining -= item.received_amount
    audit(
        session,
        actor.user_id,
        batch.id,
        f"Cash handover {batch.status}; received {batch.received_amount}; difference {batch.difference}; {payload.notes}",
    )
    await session.flush()
    return batch
