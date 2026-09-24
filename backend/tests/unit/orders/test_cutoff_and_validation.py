"""The two order rules that are pure functions: the cut-off clock and the basket rules.

Tested without a database on purpose. Both are decisions a customer sees the consequence of
immediately - "when will it arrive" and "why can't I order eight" - and both have edge cases
(midnight, the minute either side of 16:00, a merged duplicate crossing a limit) that are
far cheaper to pin here than through HTTP.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.orders import validation
from app.modules.orders.constants import QUANTITY_LIMITS
from app.modules.orders.cutoff import (
    AFTERNOON_SLOT,
    MORNING_SLOT,
    evaluate,
)
from app.modules.orders.schemas import OrderLineRequest
from app.modules.pricing.constants import CylinderType
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


def test_before_four_pm_promises_tomorrow_morning():
    result = evaluate(at_ist(2026, 9, 23, 15, 59))

    assert result.within_cutoff is True
    assert result.delivery_slot == MORNING_SLOT
    # 09:00 IST the next day, as a real UTC instant (03:30Z), not "09:00Z".
    assert result.scheduled_delivery_date == datetime(2026, 9, 24, 3, 30, tzinfo=UTC)


def test_at_exactly_four_pm_the_cutoff_has_passed():
    """16:00 is the deadline, not the last minute inside it."""
    result = evaluate(at_ist(2026, 9, 23, 16, 0))

    assert result.within_cutoff is False
    assert result.delivery_slot == AFTERNOON_SLOT
    # The day after tomorrow, 14:00 IST = 08:30Z.
    assert result.scheduled_delivery_date == datetime(2026, 9, 25, 8, 30, tzinfo=UTC)


def test_just_after_midnight_ist_is_still_within_the_same_day():
    """The UTC date is still yesterday at 00:30 IST; the promise must follow the wall clock."""
    result = evaluate(at_ist(2026, 9, 23, 0, 30))

    assert result.within_cutoff is True
    assert result.scheduled_delivery_date == datetime(2026, 9, 24, 3, 30, tzinfo=UTC)


def test_a_late_order_on_the_last_day_of_a_month_rolls_into_the_next():
    result = evaluate(at_ist(2026, 9, 30, 18, 0))

    assert result.scheduled_delivery_date.date() == datetime(2026, 10, 2, tzinfo=UTC).date()


def test_the_cutoff_message_is_the_one_the_user_reads():
    assert "4:00 PM" in evaluate(at_ist(2026, 9, 23, 10, 0)).message
    assert "cut-off has passed" in evaluate(at_ist(2026, 9, 23, 17, 0)).message


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

    # Both bounds are inclusive.
    validation.validate_basket([line(cylinder_type, minimum)], customer_type=INDUSTRIAL)
    validation.validate_basket([line(cylinder_type, maximum)], customer_type=INDUSTRIAL)

    for bad in (minimum - 1, maximum + 1):
        with pytest.raises(ApiError) as error:
            validation.validate_basket([line(cylinder_type, bad)], customer_type=INDUSTRIAL)
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
