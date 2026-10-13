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
    by_role: str | None = None,
    source: str | None = None,
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
    previous = order.status
    if previous == OrderStatus.CANCELLED.value:
        # Named separately from the generic refusal because this is the one the apps act on: a
        # delivery screen that has gone stale needs to know to reload the order, not to retry.
        raise _cancelled(order, target)
    allowed = STATUS_TRANSITIONS.get(previous, frozenset())
    if target.value not in allowed:
        raise _illegal(order, target)

    moment = now or datetime.now(UTC)
    order.status = target.value
    order.updated_at = moment
    session.add(
        OrderStatusHistory(
            order_id=order.id,
            previous_status=previous,
            status=target.value,
            changed_by_name=by_name,
            changed_by_user_id=by_user_id,
            changed_by_role=by_role,
            source=source,
            note=(note or "").strip() or None,
            changed_at=moment,
        )
    )
    return True


def note(
    session: AsyncSession,
    order: Order,
    *,
    note: str,
    by_name: str | None = None,
    by_user_id: str | None = None,
    by_role: str | None = None,
    source: str | None = None,
    now: datetime | None = None,
) -> None:
    """Record something that happened to an order **without** moving it.

    A round being handed to another driver is not a status change - the order is still
    confirmed, still waiting - but it is exactly the kind of thing somebody asks about a week
    later. The row carries the same status in and out, so the trail reads as a note on the
    timeline rather than a step in it.
    """
    moment = now or datetime.now(UTC)
    session.add(
        OrderStatusHistory(
            order_id=order.id,
            previous_status=order.status,
            status=order.status,
            changed_by_name=by_name,
            changed_by_user_id=by_user_id,
            changed_by_role=by_role,
            source=source,
            note=note.strip() or None,
            changed_at=moment,
        )
    )


def can_advance(current: str, target: OrderStatus) -> bool:
    return target.value in STATUS_TRANSITIONS.get(current, frozenset())


def _cancelled(order: Order, target: OrderStatus) -> ApiError:
    """The refusal a stale delivery screen gets, with a code it can branch on.

    A driver whose phone still shows yesterday's queue presses Start on an order the customer
    cancelled while the screen sat idle. The generic INVALID_ORDER_STATUS would tell the app the
    move was illegal; this tells it *why*, which is the difference between showing a retry and
    reloading the order as cancelled.
    """
    return ApiError(
        "ORDER_ALREADY_CANCELLED",
        http_status.HTTP_409_CONFLICT,
        f"Order {order.order_number} has already been cancelled, so it cannot be "
        f"{STATUS_BY_CODE[target.value].label.lower()}.",
    )


def _illegal(order: Order, target: OrderStatus) -> ApiError:
    """Names the order and both states: the app shows this text to an operator, unchanged.

    The order number is the part that matters on the bulk screen. Sixteen orders go in, one of
    them is already on a van, and the whole round is refused - "an order that is out for
    delivery cannot be moved to confirmed" leaves the operator to find which one by hand. With
    the number in it, the sentence says what to deselect.
    """
    current_label = (
        STATUS_BY_CODE[order.status].label.lower()
        if order.status in STATUS_BY_CODE
        else order.status
    )
    target_label = STATUS_BY_CODE[target.value].label.lower()
    return ApiError(
        "INVALID_ORDER_STATUS",
        http_status.HTTP_409_CONFLICT,
        f"Order {order.order_number} is already {current_label}, so it cannot be "
        f"{target_label}. Remove it from the selection and try again.",
    )


def check_can_move(order: Order, target: OrderStatus) -> None:
    """Refuse now if `advance()` would refuse later, without writing anything.

    For a caller that has to check the order early but moves it much later - dispatch reads the
    order first so that a stale screen is told the order was **cancelled**, rather than that the
    slip cancelling it left behind is settled. The reason is more use to the app than the
    consequence, and the app branches on the code.
    """
    if order.status == target.value:
        return
    if order.status == OrderStatus.CANCELLED.value:
        raise _cancelled(order, target)
    if not can_advance(order.status, target):
        raise _illegal(order, target)
