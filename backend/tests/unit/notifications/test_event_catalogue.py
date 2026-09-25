"""The notification catalogue, checked as a whole rather than one builder at a time.

These are structural tests. Each one states a rule that must hold for **every** event the
platform can send, so adding a new one to the catalogue is automatically held to the same
standard as the ones already there - which is the point of having a catalogue at all.

The rules exist because each has a concrete failure behind it:

* a missing `entity_id` is a notification the app cannot deep-link, so the user taps it and
  nothing happens;
* an `entity_type` the category map does not know renders as SYSTEM with no icon and no
  filter chip, which looks like a bug;
* a duplicated `event_type` collides on the outbox's uniqueness constraint, so one of the
  two events silently never arrives.
"""

import inspect
from collections import Counter

import pytest

from app.modules.notifications.constants import (
    ENTITY_CATEGORIES,
    Category,
    RecipientKind,
    Severity,
    category_of,
    reference_of,
)
from app.modules.notifications.events import DOMAINS
from app.shared.notifications.outbox import NotificationEvent

pytestmark = [pytest.mark.unit]

#: A plausible argument for every parameter name the builders use, so the whole catalogue
#: can be invoked generically. A builder that adds a parameter not listed here fails the
#: collection below, which is the reminder to add it.
SAMPLES: dict[str, object] = {
    "customer_id": "cust-1",
    "merchant_id": "merch-1",
    "user_id": "user-1",
    "driver_user_id": "user-7",
    "delivery_id": "del-1",
    "movement_id": "sm-1",
    "task_id": "TASK-000123",
    "task_title": "Verify godown stock",
    "delivery_date": "2026-09-26",
    "author_name": "Priya Nair",
    "excerpt": "Counted 180 of 200 cylinders so far.",
    "confirmation_code": "4321",
    "order_id": "ord-1",
    "order_number": "ORD-2609-0001",
    "payment_id": "pay-1",
    "invoice_id": "inv-1",
    "invoice_number": "MBGA/INV/0144",
    "application_id": "kyc-1",
    "pricing_month_id": "PRC-M-2026-09",
    "change_log_id": "4821",
    "cylinder_type": "LPG_19KG",
    "cylinder_label": "19 KG",
    "business_name": "Sharma Bakery",
    "customer_name": "Sharma Bakery",
    "customer_type": "RETAIL",
    "added_by": "Priya Nair",
    "driver_name": "Mohan Lal",
    "changed_by": "Rajesh Verma",
    "set_by": "Rajesh Verma",
    "removed_by": "Rajesh Verma",
    "reason": "BPCL base rate revised",
    "mode": "UPI",
    "slot": "09:00 AM - 01:00 PM",
    "total": 4090,
    "amount": 4090,
    "price": 1700,
    "new_price": 1800,
    "old_price": 1700,
    "standard_price": 1800,
    "balance": 500,
    "count": 42,
    "threshold": 50,
    "cylinders": 3,
    "days": 7,
}


def _builders() -> list[tuple[str, str, callable]]:
    """Every public builder in the catalogue, as (domain, name, function)."""
    found = []
    for domain in DOMAINS:
        for name, function in inspect.getmembers(domain, inspect.isfunction):
            if name.startswith("_") or function.__module__ != domain.__name__:
                continue
            found.append((domain.__name__.rsplit(".", 1)[-1], name, function))
    return found


def _call(function) -> NotificationEvent:
    """Invoke a builder with a plausible value for each of its parameters."""
    kwargs = {}
    for name, parameter in inspect.signature(function).parameters.items():
        if name not in SAMPLES:
            raise AssertionError(
                f"{function.__module__}.{function.__name__} takes '{name}', "
                f"which has no sample value - add one to SAMPLES."
            )
        kwargs[name] = SAMPLES[name]
        assert parameter.kind is not parameter.VAR_POSITIONAL
    return function(**kwargs)


ALL_BUILDERS = _builders()
CASES = [pytest.param(fn, id=f"{domain}.{name}") for domain, name, fn in ALL_BUILDERS]


def test_the_catalogue_is_not_empty():
    """Guards the collection above: a broken `_builders` would silently skip everything."""
    assert len(ALL_BUILDERS) >= 15
    domains = {domain for domain, _name, _fn in ALL_BUILDERS}
    assert domains == {"customers", "orders", "pricing", "deliveries", "payments", "stock", "tasks"}


@pytest.mark.parametrize("builder", CASES)
def test_every_event_records_what_it_is_about(builder):
    """A row with no entity is a notification the app cannot open."""
    event = _call(builder)

    assert event.entity_type, "entity_type is what the category and deep link derive from"
    assert event.entity_id, "entity_id is what the app opens"


@pytest.mark.parametrize("builder", CASES)
def test_every_event_type_is_known_to_the_category_map(builder):
    """Otherwise the row renders as SYSTEM with no icon, which reads as a bug."""
    event = _call(builder)

    assert event.entity_type in ENTITY_CATEGORIES, (
        f"{event.entity_type!r} is not in ENTITY_CATEGORIES, so this event would render as SYSTEM"
    )
    assert category_of(event.event_type, event.entity_type) is not Category.SYSTEM


@pytest.mark.parametrize("builder", CASES)
def test_every_event_is_addressed_to_a_real_audience(builder):
    event = _call(builder)

    assert event.recipient_kind in {kind.value for kind in RecipientKind}
    assert event.recipient_id


@pytest.mark.parametrize("builder", CASES)
def test_every_event_has_a_readable_title_and_body(builder):
    """These are rendered verbatim, so a placeholder left in one is visible to the user."""
    event = _call(builder)

    assert event.title and event.title == event.title.strip()
    # The outbox column is 180 characters.
    assert len(event.title) <= 180
    assert event.body and event.body == event.body.strip()
    assert "{" not in event.body, "an unformatted placeholder leaked into the message"
    assert "None" not in event.body, "an unset value leaked into the message"


@pytest.mark.parametrize("builder", CASES)
def test_every_event_carries_a_known_severity(builder):
    event = _call(builder)

    assert event.severity in {level.value for level in Severity}


def test_event_types_are_unique_across_the_whole_catalogue():
    """A duplicate collides on the outbox's uniqueness constraint and one event vanishes."""
    counts = Counter(_call(fn).event_type for _domain, _name, fn in ALL_BUILDERS)
    duplicates = {event: n for event, n in counts.items() if n > 1}

    assert not duplicates, f"duplicated event_type: {duplicates}"


@pytest.mark.parametrize("builder", CASES)
def test_optional_details_are_omitted_rather_than_printed_as_none(builder):
    """Called with only its required arguments, a message must still read cleanly."""
    signature = inspect.signature(builder)
    required = {
        name: SAMPLES[name]
        for name, parameter in signature.parameters.items()
        if parameter.default is inspect.Parameter.empty
    }
    event = builder(**required)

    assert "None" not in event.body
    assert "  " not in event.body, "an omitted detail left a double space behind"


# --- Specific wording the spec fixes (§18.8) ------------------------------------------------


def test_the_spec_titles_are_used_verbatim():
    from app.modules.notifications.events import customers, deliveries, orders, payments, stock

    assert customers.application_received("c", "b", "a").title == "Application received"
    assert customers.new_kyc_application("m", "a", "b").title == "New KYC application"
    assert customers.account_approved("c", "b", "a").title == "Account approved"
    assert customers.application_rejected("c", "b", "r", "a").title == "Application rejected"
    assert orders.order_placed_customer("c", "o", "ORD-1", 100).title == "Order placed"
    assert orders.order_placed_merchant("m", "o", "ORD-1", "n").title == "New order received"
    assert deliveries.out_for_delivery("c", "o", "ORD-1").title == "Order out for delivery"
    assert deliveries.delivered("c", "o", "ORD-1").title == "Order delivered"
    assert payments.payment_recorded("c", "p", 100, "CASH").title == "Payment received"
    assert stock.below_threshold("m", "LPG_19KG", "19 KG", 42, 50).title == "Stock below reorder threshold"


def test_the_severities_the_spec_calls_out():
    from app.modules.notifications.events import customers, orders, stock

    # §18.8 marks a rejection CRITICAL and a new order WARNING.
    assert customers.application_rejected("c", "b", "r", "a").severity == Severity.CRITICAL.value
    assert orders.order_placed_merchant("m", "o", "ORD-1", "n").severity == Severity.WARNING.value
    assert stock.out_of_stock("m", "LPG_19KG", "19 KG").severity == Severity.CRITICAL.value
    assert stock.below_threshold("m", "LPG_19KG", "19 KG", 42, 50).severity == Severity.WARNING.value


def test_the_driver_is_addressed_personally_and_never_through_the_merchant():
    """A driver is not staff, so a job must not be queued into the shared merchant bucket.

    The delivery app reads `recipient_kind = "user"` only. An assignment addressed to the
    merchant would be read by every staff member and by no driver at all.
    """
    from app.modules.notifications.events import deliveries

    for event in (
        deliveries.assigned_to_driver("user-7", "del-1", "ORD-1"),
        deliveries.unassigned_from_driver("user-7", "del-1", "ORD-1"),
        deliveries.cancelled_in_transit("user-7", "del-1", "ORD-1"),
    ):
        assert event.recipient_kind == RecipientKind.USER.value, event.event_type
        assert event.recipient_id == "user-7"
        # Keyed on the trip, so a job handed out twice is two rows rather than a collision.
        assert event.entity_type == "delivery"
        assert event.entity_id == "del-1"
        assert reference_of(event.entity_type).value == "DELIVERY"


def test_a_cancellation_in_transit_is_the_one_that_interrupts():
    from app.modules.notifications.events import deliveries

    assert deliveries.cancelled_in_transit("u", "d", "ORD-1").severity == Severity.CRITICAL.value
    # An ordinary assignment is not, or nothing would stand out.
    assert deliveries.assigned_to_driver("u", "d", "ORD-1").severity == Severity.INFO.value
    assert deliveries.unassigned_from_driver("u", "d", "ORD-1").severity == Severity.WARNING.value


def test_what_the_customer_is_told_stays_keyed_on_the_order():
    """The customer's screen is the order; only the driver's events key on the trip."""
    from app.modules.notifications.events import deliveries

    for event in (
        deliveries.out_for_delivery("cust-1", "ord-1", "ORD-1"),
        deliveries.delivered("cust-1", "ord-1", "ORD-1"),
    ):
        assert event.recipient_kind == RecipientKind.CUSTOMER.value
        assert event.entity_type == "order"


def test_every_app_has_something_addressed_to_it():
    """Three apps ship a notification screen, so all three need events that reach them.

    Written as a whole-catalogue check because the delivery app once had a bell with nothing
    in the catalogue addressed to a driver - an empty screen that looks like a bug.
    """
    kinds = {_call(fn).recipient_kind for _domain, _name, fn in ALL_BUILDERS}

    assert kinds == {
        RecipientKind.MERCHANT.value,
        RecipientKind.CUSTOMER.value,
        RecipientKind.USER.value,
    }


def test_a_stock_warning_can_fire_again_for_the_same_cylinder():
    """Keyed on the movement that crossed the reorder line, not on the cylinder type.

    The outbox is unique on `(event_type, entity_type, entity_id, recipient_kind, recipient_id)`,
    so keying on the cylinder alone would let it warn once and then never again - September's
    shortage would silently suppress November's.
    """
    from app.modules.notifications.events import stock

    september = stock.below_threshold("m", "LPG_19KG", "19 KG", 42, 50, movement_id="sm-9")
    november = stock.below_threshold("m", "LPG_19KG", "19 KG", 40, 50, movement_id="sm-77")

    assert september.entity_id != november.entity_id
    assert september.event_type == november.event_type


def test_a_stock_event_without_a_movement_still_has_a_key():
    """A caller with no movement to point at - a nightly sweep - must not write a keyless row."""
    from app.modules.notifications.events import stock

    assert stock.below_threshold("m", "LPG_19KG", "19 KG", 42, 50).entity_id == "LPG_19KG"
    assert stock.out_of_stock("m", "LPG_19KG", "19 KG").entity_id == "LPG_19KG"


def test_task_events_deep_link_to_the_task():
    """Tapping the bell row has to open the task, which is why these key on the task id.

    That is also why they are queued through `queue_repeatable`: a second update to the same task
    is the same outbox key, and a plain insert would be a duplicate-key error rather than a
    second bell row.
    """
    from app.modules.notifications.events import tasks

    for event in (
        tasks.task_assigned("m", "TASK-000123", "Verify godown stock"),
        tasks.task_updated("m", "TASK-000123", "Verify godown stock"),
        tasks.task_completed("m", "TASK-000123", "Verify godown stock"),
        tasks.task_mention("m", "TASK-000123", "Priya Nair", "please review"),
    ):
        assert event.entity_id == "TASK-000123"
        assert reference_of(event.entity_type).value == "TASK"
        assert category_of(event.event_type, event.entity_type) is Category.TASK


def test_every_task_event_goes_to_the_shared_merchant_bucket():
    """Per-user targeting is deferred platform-wide, so tasks must not invent it.

    "{author} mentioned you" says *you* to a bucket several people read - that is the spec's
    wording and the app's copy, and changing it here would put the two out of step over a word.
    """
    from app.modules.notifications.events import tasks

    for event in (
        tasks.task_assigned("m", "TASK-1", "t"),
        tasks.task_updated("m", "TASK-1", "t"),
        tasks.task_completed("m", "TASK-1", "t"),
        tasks.task_mention("m", "TASK-1", "Priya Nair", "hi"),
    ):
        assert event.recipient_kind == RecipientKind.MERCHANT.value
        assert event.recipient_id == "m"


def test_the_task_titles_the_spec_fixes():
    from app.modules.notifications.events import tasks

    assert tasks.task_assigned("m", "T", "t").title == "New task assigned"
    assert tasks.task_updated("m", "T", "t").title == "Task updated"
    assert tasks.task_completed("m", "T", "t").title == "Task marked completed"
    assert tasks.task_mention("m", "T", "Priya Nair", "hi").title == "Priya Nair mentioned you"


def test_order_events_deep_link_to_the_order():
    from app.modules.notifications.events import orders

    event = orders.order_placed_customer("c", "ord-9", "ORD-1", 100)

    assert reference_of(event.entity_type).value == "ORDER"
    assert event.entity_id == "ord-9"


def test_amounts_are_formatted_once_and_the_same_way():
    from app.modules.notifications.events import orders, payments

    assert "₹34,500" in orders.order_placed_customer("c", "o", "ORD-1", 34500).body
    assert "₹34,500" in payments.payment_recorded("c", "p", 34500, "CASH").body
