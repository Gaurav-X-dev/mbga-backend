"""Validation for dynamic, database-backed order cylinder lines."""

from fastapi import status

from app.modules.orders.constants import MAX_ORDER_LINES, QUANTITY_LIMITS
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


def merge_lines(items: list[OrderLineRequest], max_lines: int = MAX_ORDER_LINES) -> list[tuple[str, int]]:
    if not items:
        raise invalid("items", "items_required", EMPTY_BASKET_MESSAGE)
    if len(items) > max_lines:
        raise invalid(
            "items",
            "too_many_lines",
            f"An order can hold at most {max_lines} cylinder types.",
        )

    merged: dict[str, int] = {}
    for line in items:
        quantity = _whole_number(line.quantity, line.cylinder_type)
        merged[line.cylinder_type] = merged.get(line.cylinder_type, 0) + quantity
    return list(merged.items())


def validate_basket(
    items: list[OrderLineRequest],
    *,
    eligibility: dict[str, tuple[int, int | None]] | None = None,
    customer_type: str | None = None,
) -> list[tuple[str, int]]:
    """Merge lines and apply the limits configured by admin for this customer type."""
    from app.modules.pricing.constants import CylinderType

    if eligibility is None and customer_type is not None:
        ct = str(getattr(customer_type, "value", customer_type) or "").strip().upper()
        if ct == "RETAIL":
            allowed_codes = {"LPG_5KG", "LPG_10KG", "LPG_19KG"}
        else:
            allowed_codes = {"LPG_19KG", "LPG_47_5KG_L", "LPG_47_5KG_V", "LPG_422KG_HIPPO"}
        eligibility = {
            (k.value if hasattr(k, "value") else str(k)): v
            for k, v in QUANTITY_LIMITS.items()
            if (k.value if hasattr(k, "value") else str(k)) in allowed_codes
        }
    if eligibility is None:
        eligibility = {
            (k.value if hasattr(k, "value") else str(k)): v
            for k, v in QUANTITY_LIMITS.items()
        }

    max_lines = len(CylinderType) if customer_type is not None else MAX_ORDER_LINES
    lines = merge_lines(items, max_lines=max_lines)
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
