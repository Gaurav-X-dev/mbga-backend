"""Amend a pre-dispatch order without rewriting booked rates or settled documents."""

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select

from app.modules.deliveries.models import DeliverySlip, DeliverySlipItem
from app.modules.deliveries.schemas import ReassignDeliveryRequest
from app.modules.deliveries.service import DeliveryService
from app.modules.finance.advances import account, reserve
from app.modules.finance.models import AdvanceReservation
from app.modules.finance.settings import audit, policy
from app.modules.orders import transitions, validation
from app.modules.orders.amendment import OrderAmender
from app.modules.orders.models import OrderItem
from app.modules.payments.models import Invoice
from app.shared.date_time.business_calendar import business_today
from app.shared.exceptions.api_error import ApiError


def edit_version(order, items):
    content = (
        order.status,
        str(order.scheduled_delivery_date),
        order.total_amount,
        order.priority_code,
        [
            (i.cylinder_type, i.quantity, i.unit_price)
            for i in sorted(items, key=lambda i: i.cylinder_type)
        ],
    )
    return hashlib.sha256(repr(content).encode()).hexdigest()


async def amend(service, order_id, payload):
    session = service.session
    initial = await service._owned(order_id)
    from app.modules.logistics.models import Trip, TripStop
    if initial.delivery_slip_id:
        await session.scalar(select(Trip).join(TripStop, Trip.id == TripStop.trip_id).where(TripStop.delivery_id == initial.delivery_slip_id).with_for_update())
    order = await service._owned(order_id, lock=True)
    billed = await session.scalar(select(Invoice.id).where(Invoice.order_id == order.id))
    if order.status not in {"PLACED", "CONFIRMED"} or order.invoice_id or billed:
        raise ApiError(
            "ORDER_EDIT_CLOSED", 409, "Only orders awaiting dispatch can be edited or rescheduled."
        )
    slip = (
        await session.scalar(
            select(DeliverySlip)
            .where(DeliverySlip.id == order.delivery_slip_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if order.delivery_slip_id
        else None
    )
    if slip and slip.status != "SCHEDULED":
        raise ApiError("ORDER_EDIT_CLOSED", 409, "Delivery has already left the scheduled stage.")
    items = list(
        (
            await session.scalars(
                select(OrderItem).where(OrderItem.order_id == order.id).with_for_update()
            )
        ).all()
    )
    if payload.expected_version != edit_version(order, items):
        raise ApiError("ORDER_CHANGED", 409, "Order changed. Reload it before editing.")
    if payload.delivery_date and payload.delivery_date < business_today():
        raise ApiError("INVALID_DELIVERY_DATE", 422, "Select today or a future delivery date.")
    from app.modules.logistics.service import assert_slip_editable
    if order.delivery_slip_id and (payload.items is not None or payload.delivery_date is not None):
        await assert_slip_editable(session, order.delivery_slip_id)
    if payload.priority_code is not None:
        from app.modules.logistics.policy import priority_code
        order.priority_code = await priority_code(session, order.merchant_id, payload.priority_code)
        from app.modules.logistics.models import Trip, TripStop
        planned_trip = await session.scalar(select(Trip).join(TripStop, Trip.id == TripStop.trip_id).where(TripStop.delivery_id == order.delivery_slip_id).with_for_update()) if order.delivery_slip_id else None
        if planned_trip:
            planned_trip.route_preview = None
            planned_trip.version += 1
    before = order.total_amount
    if payload.items is not None:
        customer = await service._orderable_customer(order.customer_id, require_approved=True)
        quantities = dict(
            validation.validate_basket(
                payload.items,
                eligibility=await service._cylinder_eligibility(customer.customer_type),
            )
        )
        amender = OrderAmender(session, order.merchant_id, service.actor.merchant_code)
        total = await amender.projected_total(order, list(quantities.items()))
        hold = await session.scalar(
            select(AdvanceReservation)
            .where(AdvanceReservation.order_id == order.id)
            .with_for_update()
        )
        old_hold = hold.amount if hold and hold.status == "HELD" else 0
        settings = await policy(session, order.merchant_id)
        funds = await account(session, order.customer_id, order.merchant_id) if old_hold else None
        old_coverage = old_hold
        if (
            old_hold
            and settings.advanceEnabled
            and settings.autoUseAdvance
            and not settings.allowPartialAdvance
            and funds.balance - funds.reserved + old_hold < total
        ):
            old_coverage = 0
        from app.modules.credit.service import CreditLimitService

        await CreditLimitService(session).enforce_fail_open(
            order.customer_id, max(total - old_coverage, 0), replacing_order_id=order.id
        )
        await amender.amend(order, list(quantities.items()))
        if hold and hold.status == "HELD":
            funds = await account(session, order.customer_id, order.merchant_id)
            settings = await policy(session, order.merchant_id)
            amount = (
                min(total, funds.balance - funds.reserved + old_hold)
                if settings.advanceEnabled and settings.autoUseAdvance
                else min(total, old_hold)
            )
            if (
                settings.advanceEnabled
                and settings.autoUseAdvance
                and not settings.allowPartialAdvance
                and amount < total
            ):
                amount = 0
            funds.reserved += amount - old_hold
            hold.amount = amount
            hold.updated_at = datetime.now(UTC)
        else:
            await reserve(session, order, service.actor.user_id)
        if slip:
            slip.items_summary = order.items_summary
            slip_lines = {
                line.cylinder_type: line
                for line in (
                    await session.scalars(
                        select(DeliverySlipItem).where(DeliverySlipItem.slip_id == slip.id)
                    )
                ).all()
            }
            for code, line in slip_lines.items():
                if code not in quantities:
                    await session.delete(line)
                else:
                    line.quantity = quantities[code]
            for code, quantity in quantities.items():
                if code not in slip_lines:
                    session.add(
                        DeliverySlipItem(slip_id=slip.id, cylinder_type=code, quantity=quantity)
                    )
    if payload.delivery_date and payload.delivery_date != order.scheduled_delivery_date:
        if slip:
            await DeliveryService(session, service.actor, service.settings).reassign(
                slip.id,
                ReassignDeliveryRequest(deliveryDate=payload.delivery_date, reason=payload.reason),
                commit=False,
            )
        order.scheduled_delivery_date = payload.delivery_date
    order.updated_at = datetime.now(UTC)
    if slip:
        slip.updated_at = order.updated_at
    transitions.note(
        session,
        order,
        note=f"Order amended; amount {before} → {order.total_amount}; delivery {order.scheduled_delivery_date}; {payload.reason}",
        by_name=service.actor.display_name,
        by_user_id=service.actor.user_id,
        by_role=service.actor.role_label,
        source=service.actor.source,
    )
    audit(session, service.actor.user_id, order.id, f"Order amended: {payload.reason}")
    from app.shared.notifications.outbox import NotificationEvent, NotificationOutboxWriter

    notification_type = (
        "order.amended."
        + edit_version(
            order,
            list(
                (
                    await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
                ).all()
            ),
        )[:12]
    )
    outbox = NotificationOutboxWriter(session)
    outbox.queue(
        NotificationEvent(
            event_type=notification_type,
            recipient_kind="customer",
            recipient_id=order.customer_id,
            entity_type="order",
            entity_id=order.id,
            title="Order updated",
            body=f"Order {order.order_number} was updated. Delivery date: {order.scheduled_delivery_date}.",
        )
    )
    if slip and slip.driver_user_id:
        outbox.queue(
            NotificationEvent(
                event_type=notification_type,
                recipient_kind="user",
                recipient_id=slip.driver_user_id,
                recipient_channel="DELIVERY",
                entity_type="delivery",
                entity_id=slip.id,
                title="Scheduled delivery updated",
                body=f"Order {order.order_number} changed. Refresh the delivery details before dispatch.",
            )
        )
    await session.commit()
    return await service._view(order)
