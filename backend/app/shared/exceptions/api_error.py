"""Project error type for coded API errors.

Every coded error is returned as ``{"detail": {"code", "message", "fields", "request_id"}}``.
The ``detail`` wrapper is the existing project convention (the web panel reads ``detail.code``);
``fields`` and ``request_id`` are added by the exception handlers in ``app.shared.exceptions.handlers``.
"""

from typing import Any

from fastapi import HTTPException

ERROR_MESSAGES: dict[str, str] = {
    # Authentication
    "AUTH_REQUIRED": "Sign in to continue.",
    "TOKEN_EXPIRED": "Your session has expired. Refresh the session or sign in again.",
    "TOKEN_INVALID": "Your session is not valid. Sign in again.",
    "TOKEN_TYPE_NOT_ALLOWED": "This session cannot be used here. Sign in again.",
    "TOKEN_CHANNEL_MISMATCH": "This session belongs to a different app. Sign in again.",
    "SESSION_REVOKED": "You have been signed out. Sign in again.",
    "SESSION_EXPIRED": "Your session has ended. Sign in again.",
    # OTP
    "OTP_INVALID": "The code is incorrect. Check the code and try again.",
    "OTP_EXPIRED": "This code has expired. Request a new code.",
    "OTP_ATTEMPTS_EXCEEDED": "Too many incorrect attempts. Request a new code.",
    "OTP_ALREADY_USED": "This code is no longer valid. Request a new code.",
    "OTP_PURPOSE_MISMATCH": "This code is no longer valid. Request a new code.",
    "OTP_RESEND_TOO_SOON": "Wait a few seconds before requesting another code.",
    "OTP_RATE_LIMITED": "Too many codes requested. Try again later.",
    "OTP_LOCKED": "Too many incorrect codes. Try again later.",
    "OTP_DELIVERY_FAILED": "We could not send the code. Try again in a moment.",
    "RATE_LIMITED": "Too many requests. Try again later.",
    # Account state
    "NUMBER_NOT_REGISTERED": "No account was found for this mobile number.",
    "CHANNEL_NOT_ALLOWED": "This account cannot use this app.",
    "ROLE_NOT_ASSIGNED": "This account cannot use this app.",
    "PERMISSION_DENIED": "You do not have permission to do this.",
    "ACCOUNT_BLOCKED": "This account is blocked. Contact support.",
    "ACCOUNT_INACTIVE": "This account is not active. Contact support.",
    "ACCOUNT_PENDING_APPROVAL": "This account is waiting for approval.",
    "ACCOUNT_REJECTED": "This application was rejected. Contact support.",
    "ACCOUNT_SUSPENDED": "This account is suspended. Contact support.",
    "DOCUMENTS_PENDING_APPROVAL": "Your documents are still being reviewed.",
    "MERCHANT_BLOCKED": "Your business account is blocked. Contact support.",
    "MERCHANT_INACTIVE": "Your business account is not active. Contact support.",
    "MERCHANT_PENDING_APPROVAL": "Your business account is waiting for approval.",
    "MERCHANT_REJECTED": "Your business account was rejected. Contact support.",
    "DELIVERY_PROFILE_BLOCKED": "Your delivery account is blocked. Contact your merchant.",
    "DELIVERY_PROFILE_INACTIVE": "Your delivery account is not active. Contact your merchant.",
    "DELIVERY_PROFILE_PENDING_APPROVAL": "Your delivery account is waiting for approval.",
    # Customer registration
    "REGISTRATION_PROFILE_EXISTS": "A registration already exists for this mobile number.",
    "REGISTRATION_PROFILE_NOT_FOUND": "Complete your registration details first.",
    "REGISTRATION_NOT_EDITABLE": "This registration can no longer be changed.",
    "REGISTRATION_INCOMPLETE": "Complete all required registration details first.",
    "INVALID_STATUS_TRANSITION": "This action is not allowed in the current state.",
    "MERCHANT_CODE_INVALID": "The merchant code is not valid.",
    "CUSTOMER_NOT_FOUND": "We could not find this customer.",
    "REJECTION_REASON_REQUIRED": "Enter a reason for the rejection.",
    "APPLICATION_NOT_FOUND": "We could not find this application.",
    # KYC documents
    "DOCUMENT_NOT_FOUND": "We could not find this document.",
    "DOCUMENT_URL_EXPIRED": "This link has expired. Open the document again.",
    "DOCUMENT_SCAN_PENDING": "This document has not passed the security scan yet.",
    "UNSUPPORTED_FILE_TYPE": "Upload a PDF, JPG or PNG.",
    "FILE_TYPE_MISMATCH": "The file contents do not match its extension.",
    "FILE_TOO_LARGE": "The file is too large. Choose a smaller file.",
    # Notifications
    "NOTIFICATION_NOT_FOUND": "We could not find this notification.",
    # Orders
    "ORDER_NOT_FOUND": "We could not find this order.",
    "ORDER_NOT_CANCELLABLE": "This order can no longer be cancelled.",
    "NO_PREVIOUS_ORDER": "There is no earlier order to repeat yet.",
    "REORDER_NOT_POSSIBLE": "This order cannot be repeated as it is. Edit the items and try again.",
    "CYLINDER_NOT_PRICED": "This cylinder has no price set for the current month.",
    "ORDER_NOT_ALLOWED": "An order cannot be placed for this customer yet.",
    # Tasks
    "TASK_NOT_FOUND": "We could not find this task.",
    # Deliveries
    "DELIVERY_NOT_FOUND": "We could not find this delivery slip.",
    "DELIVERY_ALREADY_EXISTS": "This order is already on a delivery slip.",
    "DELIVERY_ALREADY_SETTLED": "This delivery has already been completed.",
    "DELIVERY_NOT_READY": "This delivery is not at that step yet.",
    "QR_ORDER_MISMATCH": "The order does not belong to this delivery.",
    "DELIVERY_CODE_LOCKED": "Too many incorrect codes for this delivery. Confirm it from the office.",
    "DELIVERY_USER_NOT_FOUND": "We could not find this delivery user.",
    "ORDER_NOT_DISPATCHABLE": "This order cannot be scheduled for delivery yet.",
    "INVALID_ORDER_STATUS": "This order cannot be moved to that status.",
    # Inventory
    "INSUFFICIENT_STOCK": "There is not enough stock for this. Record a refill first.",
    # Expenses
    "EXPENSE_NOT_FOUND": "We could not find this expense.",
    "EXPENSE_CATEGORY_NOT_FOUND": "We could not find this expense category.",
    # Generic
    "VALIDATION_ERROR": "Some fields are missing or invalid.",
    "INVALID_MOBILE_NUMBER": "Enter a valid 10-digit Indian mobile number.",
    "NOT_FOUND": "The requested resource was not found.",
    "CONFLICT": "This request conflicts with existing data.",
    "INTERNAL_ERROR": "Something went wrong. Try again later.",
    "SERVICE_UNAVAILABLE": "The service is temporarily unavailable. Try again later.",
}


def error_message(code: str) -> str:
    return ERROR_MESSAGES.get(code, code.replace("_", " ").capitalize() + ".")


def error_detail(code: str, message: str | None = None, fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The error envelope. `message` is what an app that reads nothing else will show.

    **One field error speaks for itself.** A refusal about a single field used to leave
    `message` as the generic "Some fields are missing or invalid", with the sentence a person
    could act on one level down in `fields[0].message` - and every app so far has shown the
    envelope. A driver who mistyped a code read "Some fields are missing"; one who claimed more
    empties than the customer held read the same thing, and reported it as an OTP fault.

    So a caller who passed **no** message - `invalid()` and everything built on it - has the
    single field's own message put in the envelope instead of the generic lookup. A caller
    who wrote one keeps it. Apps that read `fields` are unaffected: nothing moves or
    disappears, the summary just stops being useless. Two or more field errors keep the
    summary either way, because no one of them describes the refusal.
    """
    listed = fields or []
    # A caller who wrote a message keeps it, even against one field: that message is the
    # considered one. "Not enough filled 19 KG in stock (3 available, 4 needed). Record a
    # refill first." says the whole thing, where its field entry reads "3 available" - a
    # fragment meant to sit beside the input, not to stand alone. Promoting the fragment over
    # the sentence would be this fix doing the exact damage it was written to undo.
    if message is not None:
        return {"code": code, "message": message, "fields": listed}
    summary = error_message(code)
    if len(listed) == 1 and (only := (listed[0].get("message") or "").strip()):
        summary = only
    return {"code": code, "message": summary, "fields": listed}


class ApiError(HTTPException):
    def __init__(
        self,
        code: str,
        status_code: int,
        message: str | None = None,
        *,
        fields: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.code = code
        super().__init__(status_code=status_code, detail=error_detail(code, message, fields), headers=headers)
