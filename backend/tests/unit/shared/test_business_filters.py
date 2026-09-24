"""Phase B: date-range and month filters shared by list endpoints."""

from datetime import date

import pytest

from app.shared.business.filters import (
    MAX_RANGE_DAYS,
    month_range,
    validate_date_range,
    validate_month,
)
from app.shared.business.transitions import StatusMachine
from app.shared.exceptions.api_error import ApiError

pytestmark = pytest.mark.unit


def test_no_bounds_means_no_filter() -> None:
    assert validate_date_range(None, None) is None


def test_a_valid_range_covers_the_whole_end_day() -> None:
    window = validate_date_range(date(2026, 6, 1), date(2026, 6, 30))
    assert window.start_at.isoformat() == "2026-06-01T00:00:00+00:00"
    # Exclusive upper bound, so a row stamped 30 June 23:59 is still inside the range.
    assert window.end_at.isoformat() == "2026-07-01T00:00:00+00:00"


def test_one_bound_without_the_other_is_rejected() -> None:
    with pytest.raises(ApiError) as error:
        validate_date_range(date(2026, 6, 1), None)
    assert error.value.detail["fields"][0]["field"] == "to_date"


def test_a_reversed_range_is_rejected() -> None:
    with pytest.raises(ApiError) as error:
        validate_date_range(date(2026, 6, 30), date(2026, 6, 1))
    assert error.value.detail["fields"][0]["code"] == "date_range_reversed"


def test_a_range_wider_than_the_cap_is_rejected() -> None:
    with pytest.raises(ApiError) as error:
        validate_date_range(date(2025, 1, 1), date(2026, 12, 31))
    assert error.value.detail["fields"][0]["code"] == "date_range_too_wide"


def test_a_range_exactly_at_the_cap_is_accepted() -> None:
    start = date(2026, 1, 1)
    window = validate_date_range(start, date(2026, 12, 31))
    assert (window.end - window.start).days + 1 <= MAX_RANGE_DAYS


def test_a_single_day_is_a_valid_range() -> None:
    window = validate_date_range(date(2026, 6, 15), date(2026, 6, 15))
    assert (window.end_at - window.start_at).days == 1


@pytest.mark.parametrize("bad", ["2026-13", "2026/06", "06-2026", "2026", "abcd-ef"])
def test_a_malformed_month_is_rejected(bad: str) -> None:
    with pytest.raises(ApiError):
        validate_month(bad)


def test_a_valid_month_passes_through() -> None:
    assert validate_month("2026-06") == "2026-06"
    assert validate_month(None) is None


@pytest.mark.parametrize(
    ("month", "last_day"),
    [("2026-06", 30), ("2026-01", 31), ("2026-02", 28), ("2024-02", 29), ("2026-12", 31)],
)
def test_month_range_ends_on_the_real_last_day(month: str, last_day: int) -> None:
    window = month_range(month)
    assert window.start.day == 1
    assert window.end.day == last_day


# --- status transitions -------------------------------------------------------------

ORDERS = StatusMachine(
    name="order",
    allowed={
        "PLACED": frozenset({"CONFIRMED", "CANCELLED"}),
        "CONFIRMED": frozenset({"PREPARING", "CANCELLED"}),
        "PREPARING": frozenset({"OUT_FOR_DELIVERY"}),
        "OUT_FOR_DELIVERY": frozenset({"DELIVERED"}),
    },
    terminal=frozenset({"DELIVERED", "CANCELLED"}),
)


def test_a_declared_move_is_allowed() -> None:
    ORDERS.require_move("PLACED", "CONFIRMED")


def test_an_undeclared_move_is_a_conflict() -> None:
    with pytest.raises(ApiError) as error:
        ORDERS.require_move("PLACED", "DELIVERED")
    assert error.value.status_code == 409
    assert error.value.code == "INVALID_STATUS_TRANSITION"


def test_repeating_a_completed_move_is_a_conflict_not_a_silent_success() -> None:
    with pytest.raises(ApiError) as error:
        ORDERS.require_move("DELIVERED", "DELIVERED")
    assert error.value.status_code == 409


def test_terminal_states_are_reported() -> None:
    assert ORDERS.is_terminal("DELIVERED")
    assert not ORDERS.is_terminal("PLACED")
