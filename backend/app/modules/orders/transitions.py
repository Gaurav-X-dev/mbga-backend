"""Moving an order's status, for the slices that move it (spec §6, §18.3).

Extracted so the deliveries module does not write to `orders` and `order_status_history` by
hand. Every status change goes through `advance()`, which means three things are always true and
cannot drift apart as more slices land:

* the move is legal according to `STATUS_TRANSITIONS` - a delivered order cannot be dispatched,
  and a cancelled one cannot be resurrected by a slip somebody forgot to fail;
* the trail gets a row naming who moved it, which is what the tracking timeline renders and
  what a dispute reads;
* `updated_at` and the status itself change together, in the caller's transaction.

It does **not** commit and does **not** send notifications. The caller owns the transaction,
because the point of doing it this way is that the status change and the business event that
caused it - a dispatch, a confirmation - either both happen or neither does.
"""

from datetime import UTC, datetime

from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.constants import STATUS_BY_CODE, STATUS_TRANSITIONS, OrderStatus
from app.modules.orders.models import Order, OrderStatusHistory
from app.shared.exceptions.api_error import ApiError


def advance(
    session: AsyncSession,
    order: Order,
    target: OrderStatus,
    *,
    by_name: str | None = None,
    by_user_id: str | None = None,
    note: str | None = None,
    now: datetime | None = None,
) -> bool:
    """Move `order` to `target`, or raise the coded 409. Returns whether it actually moved.

    The note is what the timeline shows under the status. Spec §10.3 fixes its wording for a
    dispatch - "Vehicle {vehicle} · {driver}" - because that is what a customer ringing up to
    ask who is delivering their cylinders needs read back to them.

    The return value matters: callers queue a notification alongside the move, and the outbox is
    unique per (event, entity, recipient). Notifying on a move that did not happen is a duplicate
    key, so "did this change anything" has to be answerable rather than assumed.
    """
    if order.status == target.value:
        # Idempotent rather than an error: a retried dispatch whose slip already moved the order
        # should not fail on the order it has already moved.
        return False
    allowed = STATUS_TRANSITIONS.get(order.status, frozenset())
    if target.value not in allowed:
        raise _illegal(order.status, target)

    moment = now or datetime.now(UTC)
    order.status = target.value
    order.updated_at = moment
    session.add(
        OrderStatusHistory(
            order_id=order.id,
            status=target.value,
            changed_by_name=by_name,
            changed_by_user_id=by_user_id,
            note=(note or "").strip() or None,
            changed_at=moment,
        )
    )
    return True


def can_advance(current: str, target: OrderStatus) -> bool:
    return target.value in STATUS_TRANSITIONS.get(current, frozenset())


def _illegal(current: str, target: OrderStatus) -> ApiError:
    """Names both states in the message: the app shows it, and "invalid transition" helps nobody."""
    current_label = STATUS_BY_CODE[current].label.lower() if current in STATUS_BY_CODE else current
    target_label = STATUS_BY_CODE[target.value].label.lower()
    return ApiError(
        "INVALID_ORDER_STATUS",
        http_status.HTTP_409_CONFLICT,
        f"An order that is {current_label} cannot be moved to {target_label}.",
    )
