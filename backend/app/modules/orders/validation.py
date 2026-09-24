"""Order line validation (spec §6.3, §18.2, §18.3).

Every failure is the coded `VALIDATION_ERROR` envelope with `detail.fields[].field` naming
the input the user has to fix. The spec asks for the offending **cylinder type** as the
field on a quantity error (`fieldErrors.<CYLINDER_TYPE>` "Enter 1–50"), so that is what a
quantity failure reports - the Place Order screen highlights that one stepper rather than
the whole basket.

Duplicate lines are merged rather than rejected. Two "19 KG" rows in one body is a client
that appended instead of incrementing; the customer meant three cylinders, not an error.
"""

from fastapi import status

from app.modules.orders.constants import (
    MAX_ORDER_LINES,
    ORDER_LABELS,
    QUANTITY_LIMITS,
)
from app.modules.orders.schemas import OrderLineRequest
from app.modules.pricing.constants import INDUSTRIAL_ONLY_CYLINDERS, CylinderType
from app.shared.exceptions.api_error import ApiError

EMPTY_BASKET_MESSAGE = "Add at least one cylinder"
INDUSTRIAL_ONLY_MESSAGE = "422 KG Hippo is only available to industrial customers."


def invalid(field: str, code: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_ERROR",
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        fields=[{"field": field, "code": code, "message": message}],
    )


def merge_lines(items: list[OrderLineRequest]) -> list[tuple[CylinderType, int]]:
    """Collapse duplicate cylinder types, keeping first-seen order.

    Summing before the limit check is deliberate: 30 + 30 of a type capped at 50 is over the
    limit, and checking each row separately would let it through.
    """
    if not items:
        raise invalid("items", "items_required", EMPTY_BASKET_MESSAGE)
    if len(items) > MAX_ORDER_LINES:
        raise invalid("items", "too_many_lines", f"An order can hold at most {MAX_ORDER_LINES} cylinder types.")

    merged: dict[CylinderType, int] = {}
    for line in items:
        # Guarded before the addition: a client sending a non-integer or a bool would
        # otherwise land in the database as a quantity.
        quantity = _whole_number(line.quantity, line.cylinder_type)
        merged[line.cylinder_type] = merged.get(line.cylinder_type, 0) + quantity
    return list(merged.items())


def validate_basket(
    items: list[OrderLineRequest], *, customer_type: str | None
) -> list[tuple[CylinderType, int]]:
    """Merge, then enforce the per-type limits and the industrial-only rule.

    Returns the merged lines, ready to price.
    """
    lines = merge_lines(items)
    for cylinder_type, quantity in lines:
        _check_eligible(cylinder_type, customer_type)
        _check_quantity(cylinder_type, quantity)
    return lines


def _check_eligible(cylinder_type: CylinderType, customer_type: str | None) -> None:
    if cylinder_type in INDUSTRIAL_ONLY_CYLINDERS and (customer_type or "").upper() != "INDUSTRIAL":
        raise invalid(cylinder_type.value, "industrial_only", INDUSTRIAL_ONLY_MESSAGE)


def _check_quantity(cylinder_type: CylinderType, quantity: int) -> None:
    minimum, maximum = QUANTITY_LIMITS[cylinder_type]
    if not minimum <= quantity <= maximum:
        # The spec's wording, with an en dash: "Enter 1–50".
        raise invalid(
            cylinder_type.value,
            "quantity_out_of_range",
            f"Enter {minimum}–{maximum}",
        )


def _whole_number(value: object, cylinder_type: CylinderType) -> int:
    """Reject bools and non-integers before they can be summed.

    `True` is an `int` in Python and would quietly become a quantity of one.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid(
            cylinder_type.value,
            "quantity_not_integer",
            f"Enter a whole number of {ORDER_LABELS[cylinder_type]} cylinders.",
        )
    return value
