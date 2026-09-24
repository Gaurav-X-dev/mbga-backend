"""Phase B: integer whole-rupee money and GST-inclusive arithmetic (API_SPEC §1, §18.1)."""

import pytest

from app.shared.exceptions.api_error import ApiError
from app.shared.money import (
    MAX_MONEY,
    invoice_gst,
    line_total,
    order_total,
    split_gst,
    validate_money,
    validate_quantity,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("total", "subtotal", "gst"),
    [
        (1, 1, 0),
        (100, 85, 15),
        (1800, 1525, 275),  # the worked example in spec §18.1
        (118, 100, 18),
        (0, 0, 0),
    ],
)
def test_gst_is_extracted_from_the_total_not_added_on_top(total: int, subtotal: int, gst: int) -> None:
    split = split_gst(total)
    assert (split.subtotal, split.gst_amount) == (subtotal, gst)
    # Never adds tax on top. At ₹1 the 18% share rounds to ₹0, which is the unavoidable
    # consequence of whole-rupee money — hence <=, not <.
    assert split.subtotal <= total


@pytest.mark.parametrize("total", [1, 7, 99, 100, 101, 1799, 1800, 1801, 999_999])
def test_subtotal_plus_gst_always_equals_the_total(total: int) -> None:
    split = split_gst(total)
    assert split.subtotal + split.gst_amount == split.total_amount


def test_rounding_is_half_up_not_bankers() -> None:
    # 2242 / 1.18 = 1900.0 exactly; 2243 / 1.18 = 1900.847... -> 1901 under half-up.
    assert split_gst(2242).subtotal == 1900
    assert split_gst(2243).subtotal == 1901


def test_the_calculation_is_deterministic() -> None:
    assert [split_gst(1800) for _ in range(5)].count(split_gst(1800)) == 5


def test_line_total_multiplies_quantity() -> None:
    assert line_total(1800, 4) == 7200


def test_order_total_splits_gst_once_on_the_summed_total() -> None:
    lines = [(1800, 4), (700, 6)]  # 7200 + 4200 = 11400
    split = order_total(lines)
    assert split.total_amount == 11400
    assert split.subtotal + split.gst_amount == 11400


def test_summing_line_level_splits_can_drift_from_the_order_split() -> None:
    """Why invoice GST must come from the final total, never from summed line subtotals."""
    lines = [(101, 1)] * 7
    per_line_subtotal_sum = sum(split_gst(price * qty).subtotal for price, qty in lines)
    order = order_total(lines)
    assert order.subtotal != per_line_subtotal_sum
    assert order.subtotal + order.gst_amount == order.total_amount


def test_invoice_gst_is_derived_from_the_final_total() -> None:
    assert invoice_gst(11400).subtotal == split_gst(11400).subtotal


def test_a_zero_percent_rate_leaves_the_total_untaxed() -> None:
    split = split_gst(1000, 0)
    assert (split.subtotal, split.gst_amount) == (1000, 0)


@pytest.mark.parametrize("bad", [-1, 101, 18.0, True])
def test_an_unusable_gst_rate_is_rejected(bad) -> None:
    with pytest.raises(ValueError):
        split_gst(1000, bad)


def test_negative_money_is_rejected() -> None:
    with pytest.raises(ApiError) as error:
        validate_money(-1, field="amount")
    assert error.value.status_code == 422
    assert error.value.detail["fields"][0]["field"] == "amount"


@pytest.mark.parametrize("bad", [1.5, "100", True, None])
def test_money_must_be_a_whole_integer(bad) -> None:
    with pytest.raises(ApiError):
        validate_money(bad)


def test_money_above_the_ceiling_is_rejected() -> None:
    with pytest.raises(ApiError):
        validate_money(MAX_MONEY + 1)
    assert validate_money(MAX_MONEY) == MAX_MONEY


def test_zero_can_be_refused_where_a_positive_amount_is_required() -> None:
    assert validate_money(0) == 0
    with pytest.raises(ApiError):
        validate_money(0, allow_zero=False)


@pytest.mark.parametrize(("value", "maximum"), [(0, 50), (51, 50), (-1, None)])
def test_quantity_outside_the_allowed_band_is_rejected(value: int, maximum: int | None) -> None:
    with pytest.raises(ApiError):
        validate_quantity(value, maximum=maximum)


def test_quantity_at_the_band_edges_is_accepted() -> None:
    assert validate_quantity(1, maximum=50) == 1
    assert validate_quantity(50, maximum=50) == 50


def test_an_empty_order_is_rejected() -> None:
    with pytest.raises(ValueError):
        order_total([])
