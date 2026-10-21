"""Validation and masking for customer registration input.

Every rule here is used by **both** registration paths — customer self sign-up and the
merchant-staff create — so the two can never drift. Errors are raised in the project's
envelope with the mobile app's field names (spec §5.1 `fieldErrors`), because the app
highlights the offending input by that name.
"""

import re

from fastapi import status

from app.modules.authentication.mobile_number import (
    InvalidMobileNumberError,
    normalize_mobile_number,
)
from app.modules.customers.constants import REQUIRED_DOCUMENTS, CustomerType, KycDocumentType

PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
AADHAAR_PATTERN = re.compile(r"^[0-9]{12}$")
FSSAI_PATTERN = re.compile(r"^[0-9]{14}$")
MSME_PATTERN = re.compile(r"^UDYAM-[A-Z]{2}-[0-9]{2}-[0-9]{7}$")
PINCODE_PATTERN = re.compile(r"^[1-9][0-9]{5}$")
# Deliberately permissive: the authority on an address is the delivery driver, not a regex.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

MAX_SITES = 25


class FieldErrors:
    """Collects every invalid field so the app can highlight them all at once.

    Registration forms are long; failing on the first bad field would make the customer
    resubmit repeatedly to discover the rest.
    """

    def __init__(self) -> None:
        self.fields: list[dict[str, str]] = []

    def add(self, field: str, code: str, message: str) -> None:
        self.fields.append({"field": field, "code": code, "message": message})

    def __bool__(self) -> bool:
        return bool(self.fields)

    def raise_if_any(self) -> None:
        if self.fields:
            from app.shared.exceptions.api_error import ApiError

            raise ApiError("VALIDATION_ERROR", status.HTTP_422_UNPROCESSABLE_CONTENT, fields=self.fields)


def clean_text(value: str | None) -> str:
    """Collapse internal runs of whitespace and trim. Names are stored as typed otherwise."""
    return re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else ""


def validate_name(value: str | None, field: str, errors: FieldErrors, *, max_length: int = 160) -> str:
    text = clean_text(value)
    if not text:
        errors.add(field, "required", "This field is required.")
    elif len(text) < 2:
        errors.add(field, "too_short", "Enter at least 2 characters.")
    elif len(text) > max_length:
        errors.add(field, "too_long", f"Use at most {max_length} characters.")
    return text


def validate_email(value: str | None, errors: FieldErrors, *, field: str = "email") -> str | None:
    """Optional. Normalised to lower case; uniqueness is deliberately NOT enforced.

    The SRS gives no email-uniqueness rule, and a shared family or office address is common
    among retail customers, so inventing one here would block legitimate registrations.
    """
    if value is None or not str(value).strip():
        return None
    text = str(value).strip().lower()
    if len(text) > 255 or not EMAIL_PATTERN.match(text):
        errors.add(field, "invalid", "Enter a valid email address.")
        return None
    return text


def validate_mobile(value: str | None, errors: FieldErrors, *, field: str = "mobile") -> str | None:
    if value is None or not str(value).strip():
        errors.add(field, "required", "Enter a mobile number.")
        return None
    try:
        return normalize_mobile_number(str(value))
    except InvalidMobileNumberError:
        errors.add(field, "invalid", "Enter a valid 10-digit Indian mobile number.")
        return None


def validate_address(address, errors: FieldErrors, *, prefix: str = "deliveryAddress") -> dict[str, str | None]:
    """Validate one `Address` (spec §3.1) and return it as storable columns."""
    line1 = clean_text(getattr(address, "line1", None))
    line2 = clean_text(getattr(address, "line2", None)) or None
    city = clean_text(getattr(address, "city", None))
    state = clean_text(getattr(address, "state", None))
    pincode = re.sub(r"\s", "", str(getattr(address, "pincode", "") or ""))
    if not line1:
        errors.add(f"{prefix}.line1", "required", "Enter the address.")
    if not city:
        errors.add(f"{prefix}.city", "required", "Enter the city.")
    if not state:
        # The submitted state is kept as typed. The app defaults it to Madhya Pradesh, but
        # the backend does not overwrite a different value — that would silently misroute
        # a delivery rather than surface the mistake.
        errors.add(f"{prefix}.state", "required", "Enter the state.")
    if not PINCODE_PATTERN.match(pincode):
        errors.add(f"{prefix}.pincode", "invalid", "Enter a valid 6-digit pincode.")
    return {"line1": line1, "line2": line2, "city": city, "state": state, "pincode": pincode}


def normalize_document_number(document_type: str | KycDocumentType, raw: str | None) -> str:
    """Strip the formatting people type (spaces, hyphens, lower case) before validating."""
    code = getattr(document_type, "value", document_type)
    if code == KycDocumentType.MSME.value:
        # Hyphens are part of the published Udyam identifier, unlike Aadhaar/PAN formatting.
        return re.sub(r"\s", "", str(raw or "")).upper()
    text = re.sub(r"[\s-]", "", str(raw or ""))
    if code in {KycDocumentType.PAN.value, KycDocumentType.GST.value, KycDocumentType.MSME.value}:
        return text.upper()
    return text


def validate_document_number(document_type: KycDocumentType, raw: str | None, errors: FieldErrors) -> str | None:
    """Validate one identifier. The field name matches the app's `doc.<TYPE>.number`."""
    field = f"doc.{document_type.value}.number"
    value = normalize_document_number(document_type, raw)
    if not value:
        errors.add(field, "required", "Enter the document number.")
        return None
    patterns = {
        KycDocumentType.AADHAAR: (AADHAAR_PATTERN, "Enter the 12-digit Aadhaar number."),
        KycDocumentType.PAN: (PAN_PATTERN, "Enter a valid PAN, for example ABCDE1234F."),
        KycDocumentType.FSSAI: (FSSAI_PATTERN, "Enter the 14-digit FSSAI licence number."),
        KycDocumentType.GST: (GSTIN_PATTERN, "Enter a valid 15-character GSTIN."),
        KycDocumentType.MSME: (
            MSME_PATTERN,
            "Enter a valid Udyam number, for example UDYAM-MP-01-1234567.",
        ),
    }
    pattern, message = patterns[document_type]
    if not pattern.match(value):
        errors.add(field, "invalid", message)
        return None
    return value


def validate_dynamic_document_number(document_type: str, raw: str | None, definition, errors: FieldErrors) -> str | None:
    """Validate an identifier using the administrator-managed catalogue definition."""
    code = document_type.upper()
    field = f"doc.{code}.number"
    value = normalize_document_number(code, raw)
    if not value:
        errors.add(field, "required", "Enter the document number.")
        return None
    if definition.min_length is not None and len(value) < definition.min_length:
        errors.add(field, "invalid", f"Enter at least {definition.min_length} characters.")
        return None
    if definition.max_length is not None and len(value) > definition.max_length:
        errors.add(field, "invalid", f"Enter at most {definition.max_length} characters.")
        return None
    if definition.number_pattern:
        try:
            matches = re.fullmatch(definition.number_pattern, value)
        except re.error:
            errors.add(field, "configuration_error", "This document type is not configured correctly.")
            return None
        if not matches:
            errors.add(field, "invalid", f"Enter a valid {definition.label} number.")
            return None
    return value


def mask_document_number(document_type: str | KycDocumentType, value: str) -> str:
    """The only form of an identifier that leaves the backend (spec §3.4).

    Each mask keeps just enough for a reviewer to match the number against the document
    image on screen, and no more.
    """
    code = getattr(document_type, "value", document_type)
    if code == KycDocumentType.AADHAAR.value:
        return f"XXXX XXXX {value[-4:]}"
    if code == KycDocumentType.PAN.value:
        # The last five (serial digits + check letter) are what a reviewer cross-checks.
        return f"XXXXX{value[-5:]}"
    if code == KycDocumentType.FSSAI.value:
        return f"{'X' * 10}{value[-4:]}"
    if code == KycDocumentType.MSME.value:
        return f"UDYAM-XX-XX-{'X' * 3}{value[-4:]}"
    # GSTIN: the state code is not secret and identifies the registration at a glance.
    if code == KycDocumentType.GST.value:
        return f"{value[:2]}{'X' * 10}{value[-3:]}"
    return f"{'X' * max(len(value) - 4, 0)}{value[-4:]}"


def required_documents(customer_type: CustomerType) -> tuple[KycDocumentType, ...]:
    return REQUIRED_DOCUMENTS[customer_type]
