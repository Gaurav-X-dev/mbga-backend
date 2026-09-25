"""Moving an order's status (spec §6, §18.3).

Extracted into `orders/transitions.py` so the deliveries module does not write to `orders` and
`order_status_history` by hand. These tests pin the guarantees that made it worth extracting: the
move is legal, the trail records who made it, and an illegal move says so in words the app shows.

No database: `advance()` takes a session only to add the history row, so a recorder stands in.
"""

from datetime import UTC, datetime

import pytest

from app.modules.orders import transitions
from app.modules.orders.constants import OrderStatus
from app.modules.orders.models import Order, OrderStatusHistory
from app.shared.exceptions.api_error import ApiError

pytestmark = [pytest.mark.unit]


class Recorder:
    """Stands in for the session: remembers what would have been added."""

    def __init__(self) -> None:
        self.added: list[OrderStatusHistory] = []

    def add(self, row) -> None:
        self.added.append(row)


def order(status: OrderStatus) -> Order:
    return Order(id="ord-1", order_number="ORD-2609-0001", status=status.value, updated_at=datetime.now(UTC))


# --- Legal moves ---------------------------------------------------------------------------------


def test_a_confirmed_order_goes_straight_out_for_delivery():
    """There is no step between.

    Dispatching the slip is the only thing that moves it, and that happens the moment the
    cylinders are actually loaded - which is what `PREPARING` was supposed to describe.
    """
    session, row = Recorder(), order(OrderStatus.CONFIRMED)

    transitions.advance(
        session,
        row,
        OrderStatus.OUT_FOR_DELIVERY,
        by_name="Priya Nair",
        note="Vehicle MP09 GH 4521 · Arjun",
    )

    assert row.status == "OUT_FOR_DELIVERY"
    assert len(session.added) == 1
    assert (session.added[0].status, session.added[0].changed_by_name) == (
        "OUT_FOR_DELIVERY",
        "Priya Nair",
    )
    assert session.added[0].note == "Vehicle MP09 GH 4521 · Arjun"


def test_an_order_on_the_van_can_be_delivered():
    session, row = Recorder(), order(OrderStatus.OUT_FOR_DELIVERY)

    transitions.advance(session, row, OrderStatus.DELIVERED)

    assert row.status == "DELIVERED"


def test_the_status_and_the_timestamp_move_together():
    """A status change with a stale `updated_at` makes "what changed recently" a lie."""
    session, row = Recorder(), order(OrderStatus.CONFIRMED)
    before = row.updated_at

    transitions.advance(session, row, OrderStatus.OUT_FOR_DELIVERY)

    assert row.updated_at >= before


# --- Illegal moves --------------------------------------------------------------------------------


def test_a_placed_order_cannot_jump_onto_the_van():
    """It has not been accepted yet, so there is nothing to load a van for."""
    session, row = Recorder(), order(OrderStatus.PLACED)

    with pytest.raises(ApiError) as caught:
        transitions.advance(session, row, OrderStatus.OUT_FOR_DELIVERY)

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "INVALID_ORDER_STATUS"
    assert session.added == [], "nothing is recorded for a move that did not happen"


def test_a_delivered_order_cannot_be_moved_again():
    """It is a receipt."""
    session, row = Recorder(), order(OrderStatus.DELIVERED)

    with pytest.raises(ApiError):
        transitions.advance(session, row, OrderStatus.OUT_FOR_DELIVERY)


def test_a_cancelled_order_cannot_be_resurrected():
    """Which is what stops a slip somebody forgot to fail from reviving it."""
    session, row = Recorder(), order(OrderStatus.CANCELLED)

    with pytest.raises(ApiError):
        transitions.advance(session, row, OrderStatus.OUT_FOR_DELIVERY)


def test_the_refusal_names_both_states():
    """The app shows this message, and "invalid transition" helps nobody."""
    session, row = Recorder(), order(OrderStatus.CONFIRMED)

    with pytest.raises(ApiError) as caught:
        transitions.advance(session, row, OrderStatus.DELIVERED)

    message = caught.value.detail["message"]
    assert "confirmed" in message
    assert "delivered" in message


# --- Idempotence -----------------------------------------------------------------------------------


def test_moving_to_the_status_it_is_already_in_does_nothing():
    """A retried dispatch whose slip already moved the order must not fail on the order."""
    session, row = Recorder(), order(OrderStatus.OUT_FOR_DELIVERY)

    moved = transitions.advance(session, row, OrderStatus.OUT_FOR_DELIVERY)

    assert moved is False
    assert row.status == "OUT_FOR_DELIVERY"
    assert session.added == [], "no duplicate row in the trail"


def test_a_real_move_says_so():
    """Callers queue a notification on the strength of this, and the outbox is unique per
    (event, entity, recipient) - so notifying on a move that did not happen is a 500."""
    session, row = Recorder(), order(OrderStatus.CONFIRMED)

    assert transitions.advance(session, row, OrderStatus.OUT_FOR_DELIVERY) is True


def test_can_advance_answers_without_raising():
    assert transitions.can_advance("CONFIRMED", OrderStatus.OUT_FOR_DELIVERY)
    assert not transitions.can_advance("PLACED", OrderStatus.OUT_FOR_DELIVERY)
    assert not transitions.can_advance("DELIVERED", OrderStatus.DELIVERED)


# --- The trail --------------------------------------------------------------------------------------


def test_an_empty_note_is_stored_as_nothing():
    """So the app can test for a note rather than for a blank string."""
    session, row = Recorder(), order(OrderStatus.CONFIRMED)

    transitions.advance(session, row, OrderStatus.OUT_FOR_DELIVERY, note="   ")

    assert session.added[0].note is None


def test_the_trail_records_the_user_as_well_as_the_name():
    """The name is what is displayed; the id is what an audit follows."""
    session, row = Recorder(), order(OrderStatus.CONFIRMED)

    transitions.advance(session, row, OrderStatus.OUT_FOR_DELIVERY, by_name="Priya Nair", by_user_id="user-9")

    assert (session.added[0].changed_by_name, session.added[0].changed_by_user_id) == (
        "Priya Nair",
        "user-9",
    )


def test_a_system_move_records_no_actor():
    """Null rather than a placeholder: the app shows no actor at all for these."""
    session, row = Recorder(), order(OrderStatus.CONFIRMED)

    transitions.advance(session, row, OrderStatus.OUT_FOR_DELIVERY)

    assert session.added[0].changed_by_name is None
