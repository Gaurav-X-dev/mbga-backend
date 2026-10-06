"""The two order rules that are pure functions: the cut-off clock and the basket rules.

Tested without a database on purpose. Both are decisions a customer sees the consequence of
immediately - "when will it arrive" and "why can't I order eight" - and both have edge cases
(midnight, the minute either side of 16:00, a merged duplicate crossing a limit) that are
far cheaper to pin here than through HTTP.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.modules.orders import validation
from app.modules.orders.constants import QUANTITY_LIMITS
from app.modules.orders.cutoff import clock_12h, clock_24h, evaluate
from app.modules.platform_settings.models import DEFAULT_ORDER_CUTOFF_HOUR
from app.modules.orders.schemas import OrderLineRequest
from app.modules.pricing.constants import (
    DEFAULT_STANDARD_RATES,
    CylinderType,
    cylinders_for,
)
from app.shared.exceptions.api_error import ApiError

pytestmark = [pytest.mark.unit]

INDUSTRIAL = "INDUSTRIAL"
RETAIL = "RETAIL"


def at_ist(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """An IST wall-clock moment, as the UTC instant the server would see."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC) - timedelta(hours=5, minutes=30)


def line(cylinder_type: CylinderType, quantity: int) -> OrderLineRequest:
    return OrderLineRequest(cylinderType=cylinder_type.value, quantity=quantity)


# --- Cut-off (spec §18.4) ---------------------------------------------------------------


def test_before_four_pm_promises_the_same_day():
    """There is still a working afternoon left, so the van goes today."""
    result = evaluate(at_ist(2026, 9, 23, 15, 59), hour=16)

    assert result.within_cutoff is True
    # A calendar day, not an instant. There is no delivery slot: the godown never scheduled
    # against one, so promising a morning or afternoon window was a promise that got broken.
    assert result.scheduled_delivery_date == date(2026, 9, 23)


def test_at_exactly_four_pm_the_cutoff_has_passed():
    """16:00 is the deadline, not the last minute inside it."""
    result = evaluate(at_ist(2026, 9, 23, 16, 0), hour=16)

    assert result.within_cutoff is False
    assert result.scheduled_delivery_date == date(2026, 9, 24)


def test_the_cutoff_is_read_on_an_ist_wall_clock():
    """23:30 UTC is already the 24th in IST, and the order belongs to the merchant's day.

    Evaluating this in UTC would move the cut-off to 21:30 IST and promise same-day delivery for
    five and a half hours a day that the godown cannot honour.
    """
    result = evaluate(datetime(2026, 9, 23, 23, 30, tzinfo=UTC), hour=16)

    assert result.within_cutoff is True
    assert result.scheduled_delivery_date == date(2026, 9, 24)


def test_there_is_no_slot_on_the_cutoff_at_all():
    """A regression guard: the field was removed, not left empty."""
    assert not hasattr(evaluate(at_ist(2026, 9, 23, 10, 0), hour=16), "delivery_slot")


def test_just_after_midnight_ist_is_still_within_the_same_day():
    """The UTC date is still yesterday at 00:30 IST; the promise must follow the wall clock."""
    result = evaluate(at_ist(2026, 9, 23, 0, 30), hour=16)

    assert result.within_cutoff is True
    assert result.scheduled_delivery_date == date(2026, 9, 23)


def test_a_late_order_on_the_last_day_of_a_month_rolls_into_the_next():
    result = evaluate(at_ist(2026, 9, 30, 18, 0), hour=16)

    assert result.scheduled_delivery_date == date(2026, 10, 1)


def test_the_cutoff_message_is_the_one_the_user_reads():
    assert "same-day" in evaluate(at_ist(2026, 9, 23, 10, 0), hour=16).message
    assert "cut-off has passed" in evaluate(at_ist(2026, 9, 23, 17, 0), hour=16).message


# --- A configurable hour ---------------------------------------------------------------------
#
# The hour is `ORDER_CUTOFF_HOUR` rather than a constant, so a merchant extending their day is a
# line in `.env` and a restart. What has to hold is that *everything* follows it: the moment the
# day rolls over, the 24-hour string an app parses, and the sentence a customer reads. A screen
# promising four o'clock while the godown works to six is the failure this guards against.


def test_a_later_cutoff_keeps_the_afternoon_on_the_same_day():
    """17:00 is past four and inside six."""
    late_afternoon = at_ist(2026, 9, 23, 17, 0)

    assert evaluate(late_afternoon, hour=16).within_cutoff is False
    assert evaluate(late_afternoon, hour=18).within_cutoff is True
    assert evaluate(late_afternoon, hour=18).scheduled_delivery_date == date(2026, 9, 23)


def test_an_earlier_cutoff_pushes_the_afternoon_to_tomorrow():
    midday = at_ist(2026, 9, 23, 12, 30)

    assert evaluate(midday, hour=16).scheduled_delivery_date == date(2026, 9, 23)
    assert evaluate(midday, hour=12).scheduled_delivery_date == date(2026, 9, 24)


def test_the_published_time_follows_the_configured_hour():
    """The apps parse this, so it cannot keep saying 16:00 after the hour moves."""
    assert evaluate(at_ist(2026, 9, 23, 9, 0), hour=16).cutoff_time == "16:00"
    assert evaluate(at_ist(2026, 9, 23, 9, 0), hour=18).cutoff_time == "18:00"
    assert evaluate(at_ist(2026, 9, 23, 7, 0), hour=9).cutoff_time == "09:00"


def test_the_message_names_the_configured_hour_in_words():
    """Derived from the same number, so the sentence cannot drift from the rule."""
    assert "6:00 PM" in evaluate(at_ist(2026, 9, 23, 9, 0), hour=18).message
    assert "4:00 PM" in evaluate(at_ist(2026, 9, 23, 9, 0), hour=16).message
    assert "9:00 AM" in evaluate(at_ist(2026, 9, 23, 7, 0), hour=9).message


def test_midday_and_midnight_read_as_people_say_them():
    """12 is noon and 0 is midnight; neither is "0:00 PM" or "12:00 PM" by accident."""
    assert clock_12h(12) == "12:00 PM"
    assert clock_12h(0) == "12:00 AM"
    assert clock_12h(13) == "1:00 PM"
    assert clock_12h(11) == "11:00 AM"


def test_the_shipped_default_is_still_four_pm():
    """What a fresh install starts with, before anybody changes it from the panel."""
    assert DEFAULT_ORDER_CUTOFF_HOUR == 16
    assert evaluate(at_ist(2026, 9, 23, 9, 0), hour=16).cutoff_time == clock_24h(DEFAULT_ORDER_CUTOFF_HOUR)


# --- Basket rules (spec §6.3, §18.3) -------------------------------------------------------


def test_an_empty_basket_names_the_items_field():
    with pytest.raises(ApiError) as error:
        validation.validate_basket([], customer_type=RETAIL)

    assert error.value.status_code == 422
    assert error.value.detail["fields"][0]["field"] == "items"
    assert error.value.detail["fields"][0]["message"] == validation.EMPTY_BASKET_MESSAGE


def test_duplicate_lines_are_merged_not_rejected():
    """Two 19 KG rows is a client that appended instead of incrementing."""
    lines = validation.validate_basket(
        [line(CylinderType.LPG_19KG, 2), line(CylinderType.LPG_19KG, 1)], customer_type=RETAIL
    )

    assert lines == [(CylinderType.LPG_19KG, 3)]


def test_merged_duplicates_are_limit_checked_on_the_total():
    """30 + 30 of a type capped at 50 is over the limit, even though each row is legal."""
    with pytest.raises(ApiError) as error:
        validation.validate_basket(
            [line(CylinderType.LPG_19KG, 30), line(CylinderType.LPG_19KG, 30)],
            customer_type=RETAIL,
        )

    assert error.value.detail["fields"][0]["field"] == CylinderType.LPG_19KG.value


def test_merging_keeps_first_seen_order():
    lines = validation.validate_basket(
        [line(CylinderType.LPG_19KG, 1), line(CylinderType.LPG_5KG, 1), line(CylinderType.LPG_19KG, 1)],
        customer_type=RETAIL,
    )

    assert [kind for kind, _ in lines] == [CylinderType.LPG_19KG, CylinderType.LPG_5KG]


@pytest.mark.parametrize("cylinder_type", list(CylinderType))
def test_each_type_enforces_its_own_limits(cylinder_type):
    minimum, maximum = QUANTITY_LIMITS[cylinder_type]
    customer_type = (
        RETAIL
        if cylinder_type in {CylinderType.LPG_5KG, CylinderType.LPG_10KG}
        else INDUSTRIAL
    )

    # Both bounds are inclusive.
    validation.validate_basket([line(cylinder_type, minimum)], customer_type=customer_type)
    validation.validate_basket([line(cylinder_type, maximum)], customer_type=customer_type)

    for bad in (minimum - 1, maximum + 1):
        with pytest.raises(ApiError) as error:
            validation.validate_basket([line(cylinder_type, bad)], customer_type=customer_type)
        # The spec asks for the cylinder type as the field, so the stepper highlights.
        assert error.value.detail["fields"][0]["field"] == cylinder_type.value
        assert error.value.detail["fields"][0]["message"] == f"Enter {minimum}–{maximum}"


def test_hippo_is_refused_to_a_retail_customer():
    with pytest.raises(ApiError) as error:
        validation.validate_basket([line(CylinderType.LPG_422KG_HIPPO, 1)], customer_type=RETAIL)

    assert error.value.detail["fields"][0]["message"] == validation.INDUSTRIAL_ONLY_MESSAGE


def test_hippo_is_allowed_to_an_industrial_customer():
    lines = validation.validate_basket(
        [line(CylinderType.LPG_422KG_HIPPO, 5)], customer_type=INDUSTRIAL
    )

    assert lines == [(CylinderType.LPG_422KG_HIPPO, 5)]


def test_a_boolean_quantity_is_not_a_quantity():
    """`True` is an `int` in Python and would otherwise become one cylinder."""
    payload = OrderLineRequest.model_construct(cylinder_type=CylinderType.LPG_5KG, quantity=True)

    with pytest.raises(ApiError) as error:
        validation.validate_basket([payload], customer_type=RETAIL)

    assert error.value.detail["fields"][0]["code"] == "quantity_not_integer"


def test_more_lines_than_cylinder_types_is_rejected():
    payload = [line(CylinderType.LPG_5KG, 1)] * (len(CylinderType) + 1)

    with pytest.raises(ApiError) as error:
        validation.validate_basket(payload, customer_type=RETAIL)

    assert error.value.detail["fields"][0]["field"] == "items"


# --- The opening rate card ---------------------------------------------------------------------


def test_every_cylinder_type_has_an_opening_rate():
    """The invariant that `LPG_10KG` broke, and the one that made it invisible everywhere.

    A pricing month opens from this card, and later months open by copying the one before. A
    type with no rate here therefore gets no row in any month, this one or any that follows -
    so it never appears on the rate card, the per-customer override screen, or the order form
    that prices against them. Adding a cylinder type without a rate is the whole bug.
    """
    missing = [kind.value for kind in CylinderType if kind not in DEFAULT_STANDARD_RATES]
    assert not missing, f"no opening rate for: {missing}"


def test_a_retail_customer_can_be_priced_for_everything_they_may_order():
    """Offering a cylinder the price card cannot price is an order that cannot be placed."""
    for kind in cylinders_for("RETAIL"):
        assert kind in DEFAULT_STANDARD_RATES, f"{kind.value} is orderable but has no rate"
    for kind in cylinders_for("INDUSTRIAL"):
        assert kind in DEFAULT_STANDARD_RATES, f"{kind.value} is orderable but has no rate"
