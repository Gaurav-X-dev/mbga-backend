"""Field and state rules for a delivery slip (spec §10.3, §10.4).

Every failure is the coded `VALIDATION_ERROR` envelope with `detail.fields[].field` naming the
input to fix, and the messages are spec §10.4's own wording - "Incorrect OTP", "Invalid count" -
because the app shows them verbatim under the field.

The state rules live here too, rather than in the service, so "when may a slip be raised" and
"who may be on the crew" can be read in one place and tested without a database.
"""

from fastapi import status as http_status

from app.modules.deliveries.constants import (
    MAX_NOTE_LENGTH,
    SLIPPABLE_ORDER_STATUSES,
    SUPPORTED_CONFIRMATION_METHODS,
    ConfirmationMethod,
    DeliveryStatus,
)
from app.modules.orders.constants import STATUS_BY_CODE
from app.modules.orders.models import Order
from app.shared.exceptions.api_error import ApiError

INCORRECT_CODE_MESSAGE = "Incorrect OTP"
INVALID_COUNT_MESSAGE = "Invalid count"
#: Indian commercial plates: "MP09 GH 4521". Kept loose on purpose - BS, military and older
#: series all differ, and refusing a real van at the gate over a format is worse than storing a
#: slightly odd string. Only length and character class are enforced.
VEHICLE_ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -")


def invalid(field: str, code: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_ERROR",
        http_status.HTTP_422_UNPROCESSABLE_CONTENT,
        fields=[{"field": field, "code": code, "message": message}],
    )


def bad_code() -> ApiError:
    """Spec §10.4: `422 fieldErrors.otp` "Incorrect OTP"."""
    return invalid("otp", "incorrect_otp", INCORRECT_CODE_MESSAGE)


# --- Creating a slip --------------------------------------------------------------------------


def check_order_state(order: Order) -> None:
    """Only an accepted order may have a van loaded for it.

    `PLACED` is excluded deliberately: it has not been reviewed, and loading cylinders for an
    order nobody has confirmed is how a van goes out for an order that is then cancelled.
    """
    if order.status in SLIPPABLE_ORDER_STATUSES:
        return
    label = STATUS_BY_CODE[order.status].label.lower() if order.status in STATUS_BY_CODE else order.status
    raise ApiError(
        "ORDER_NOT_DISPATCHABLE",
        http_status.HTTP_409_CONFLICT,
        f"Order {order.order_number} is {label}. Confirm it before scheduling a delivery.",
    )


def check_vehicle_number(value: str) -> str:
    """Upper-cased and trimmed. A vehicle number is read off a plate, so case is noise."""
    vehicle = " ".join((value or "").upper().split())
    if len(vehicle) < 4:
        raise invalid("vehicleNumber", "vehicle_required", "Enter the vehicle number")
    if not set(vehicle) <= VEHICLE_ALLOWED:
        raise invalid("vehicleNumber", "vehicle_invalid", "Enter a valid vehicle number")
    return vehicle


def check_confirmation_method(method: ConfirmationMethod) -> ConfirmationMethod:
    """Refuse a method no screen can complete.

    `SIGNATURE` and `PHOTO` are in the enum for later phases. Accepting one now would create a
    slip that no app screen can confirm, and the only way out would be a database edit.
    """
    if method not in SUPPORTED_CONFIRMATION_METHODS:
        allowed = " or ".join(sorted(item.value for item in SUPPORTED_CONFIRMATION_METHODS))
        raise invalid(
            "confirmationMethod",
            "confirmation_method_unsupported",
            f"Only {allowed} confirmation is available in this version.",
        )
    return method


def check_crew(profile, *, role: str):
    """The named driver or helper must be this merchant's, active and approved.

    `profile` is `None` either because no id was given - handled by the caller - or because the
    id belongs to another merchant, which is reported as a 404 rather than a 403 so staff ids
    cannot be probed across tenants.
    """
    if profile is None:
        raise ApiError(
            "DELIVERY_USER_NOT_FOUND",
            http_status.HTTP_404_NOT_FOUND,
            f"We could not find this {role}.",
        )
    if profile.approval_status != "APPROVED":
        raise invalid(
            f"{role}UserId",
            f"{role}_not_approved",
            f"This {role}'s account is still waiting for approval.",
        )
    if profile.status != "ACTIVE":
        raise invalid(
            f"{role}UserId",
            f"{role}_not_active",
            f"This {role}'s account is not active.",
        )
    return profile


def resolve_driver_name(payload, account_name: str | None) -> str:
    """Whose name goes on the slip.

    The driver's **account** name wins when a driver was picked from the list, so the slip cannot
    claim a different name from the phone it notifies - and so the customer's "… is on the way"
    names a person rather than an employee code. A typed name is accepted only for a hired van
    with no account, in which case nobody is notified and the office tells the driver directly.
    """
    if account_name:
        return account_name[:160]
    typed = (payload.driver_name or "").strip()
    if not typed:
        raise invalid("driverName", "driver_required", "Choose a driver or enter the driver's name")
    return typed[:160]


def resolve_helper_name(payload, account_name: str | None) -> str | None:
    if account_name:
        return account_name[:160]
    return (payload.helper_name or "").strip() or None


# --- Confirming -------------------------------------------------------------------------------


def check_empties(collected: int | None, allocated: int) -> int:
    """`0 <= n <= cylindersAllocated` (spec §10.4).

    The upper bound is not pedantry: more empties than cylinders delivered means the driver is
    booking somebody else's cylinders onto this slip, and the empty bucket stops reconciling.
    """
    if collected is None or isinstance(collected, bool) or not isinstance(collected, int):
        raise invalid("emptiesCollected", "empties_invalid", INVALID_COUNT_MESSAGE)
    if collected < 0 or collected > allocated:
        raise invalid("emptiesCollected", "empties_out_of_range", INVALID_COUNT_MESSAGE)
    return collected


def check_note(value: str | None) -> str | None:
    note = (value or "").strip()
    if len(note) > MAX_NOTE_LENGTH:
        raise invalid("note", "note_too_long", f"Keep the note under {MAX_NOTE_LENGTH} characters")
    return note or None


def not_ready_message(slip_number: str, current: str, ready: DeliveryStatus) -> str:
    """Spec §10.4 asks for "not been dispatched yet" specifically, so say which step is missing."""
    if ready is DeliveryStatus.DISPATCHED:
        return f"Slip {slip_number} has not been dispatched yet."
    if current == DeliveryStatus.FAILED.value:
        return f"Slip {slip_number} failed and cannot be dispatched. Raise a new slip."
    return f"Slip {slip_number} is {current.lower()} and cannot be dispatched."
