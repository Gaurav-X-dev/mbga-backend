"""Validation for dynamic, database-backed order cylinder lines."""

from fastapi import status

from app.modules.orders.constants import MAX_ORDER_LINES
from app.modules.orders.schemas import OrderLineRequest
from app.shared.exceptions.api_error import ApiError

EMPTY_BASKET_MESSAGE = "Add at least one cylinder"
INELIGIBLE_CYLINDER_MESSAGE = "This cylinder type is not available for this customer type."
INDUSTRIAL_ONLY_MESSAGE = INELIGIBLE_CYLINDER_MESSAGE


def invalid(field: str, code: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_ERROR",
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        fields=[{"field": field, "code": code, "message": message}],
    )


def merge_lines(items: list[OrderLineRequest]) -> list[tuple[str, int]]:
    if not items:
        raise invalid("items", "items_required", EMPTY_BASKET_MESSAGE)
    if len(items) > MAX_ORDER_LINES:
        raise invalid(
            "items",
            "too_many_lines",
            f"An order can hold at most {MAX_ORDER_LINES} cylinder types.",
        )

    merged: dict[str, int] = {}
    for line in items:
        quantity = _whole_number(line.quantity, line.cylinder_type)
        merged[line.cylinder_type] = merged.get(line.cylinder_type, 0) + quantity
    return list(merged.items())


def validate_basket(
    items: list[OrderLineRequest],
    *,
    eligibility: dict[str, tuple[int, int | None]],
) -> list[tuple[str, int]]:
    """Merge lines and apply the limits configured by admin for this customer type."""
    lines = merge_lines(items)
    for cylinder_type, quantity in lines:
        limits = eligibility.get(cylinder_type)
        if limits is None:
            raise invalid(
                cylinder_type,
                "customer_type_not_eligible",
                INELIGIBLE_CYLINDER_MESSAGE,
            )
        minimum, maximum = limits
        if quantity < minimum or (maximum is not None and quantity > maximum):
            upper = str(maximum) if maximum is not None else "any"
            raise invalid(
                cylinder_type,
                "quantity_out_of_range",
                f"Enter {minimum}–{upper}",
            )
    return lines


def _whole_number(value: object, cylinder_type: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid(
            cylinder_type,
            "quantity_not_integer",
            "Enter a whole number of cylinders.",
        )
    return value
