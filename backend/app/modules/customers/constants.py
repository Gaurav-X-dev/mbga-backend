"""Customer, KYC and document vocabularies, plus the backend/mobile mapping layer.

The mobile contract (API_SPEC §2) and this backend grew separately, so their status words
differ. Rather than add a second set of columns, one mapping lives here and every response
mapper goes through it. The database keeps the backend words; the apps see theirs.
"""

from enum import StrEnum

from app.modules.authentication.account_state import (
    CUSTOMER_APPROVED,
    CUSTOMER_DOCUMENTS_PENDING,
    CUSTOMER_PROFILE_INCOMPLETE,
    CUSTOMER_REJECTED,
    CUSTOMER_SUSPENDED,
    CUSTOMER_UNDER_REVIEW,
)


class CustomerType(StrEnum):
    RETAIL = "RETAIL"
    INDUSTRIAL = "INDUSTRIAL"


class KycDocumentType(StrEnum):
    AADHAAR = "AADHAAR"
    PAN = "PAN"
    FSSAI = "FSSAI"
    GST = "GST"


class UploadType(StrEnum):
    """What an upload is *for*, which is wider than KYC now that tasks attach files too.

    Kept apart from `KycDocumentType` on purpose. That enum drives which documents a customer type
    must supply and which slot a file may be attached to; adding `TASK_ATTACHMENT` to it would put
    a task screenshot in the list of things a registration can be completed with.
    """

    AADHAAR = "AADHAAR"
    PAN = "PAN"
    FSSAI = "FSSAI"
    GST = "GST"
    TASK_ATTACHMENT = "TASK_ATTACHMENT"

    @property
    def is_kyc(self) -> bool:
        return self is not UploadType.TASK_ATTACHMENT


class PricingTier(StrEnum):
    STANDARD = "STANDARD"
    BULK = "BULK"
    KEY_ACCOUNT = "KEY_ACCOUNT"


class KycStatus(StrEnum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ApplicationStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DocumentStatus(StrEnum):
    """The mobile contract's document vocabulary (spec 3.4)."""

    UPLOADED = "UPLOADED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


# The stored value is the backend's own word. `AccountStateResolver` - part of the frozen
# authentication layer - refuses a customer sign-in while any mandatory document is not
# "APPROVED", so that is what a verified document is stored as. The mobile contract calls the
# same state VERIFIED, and the response mapper translates. Two vocabularies, one column.
DOCUMENT_APPROVED = "APPROVED"

DOCUMENT_STATUS_TO_MOBILE: dict[str, str] = {
    DOCUMENT_APPROVED: DocumentStatus.VERIFIED.value,
    DocumentStatus.VERIFIED.value: DocumentStatus.VERIFIED.value,
    DocumentStatus.UPLOADED.value: DocumentStatus.UPLOADED.value,
    DocumentStatus.REJECTED.value: DocumentStatus.REJECTED.value,
}


def to_mobile_document_status(value: str | None) -> str:
    return DOCUMENT_STATUS_TO_MOBILE.get(value or "", DocumentStatus.UPLOADED.value)


class ScanStatus(StrEnum):
    """Malware-scan state. `PENDING` is the integration point for a real scanner."""

    PENDING = "PENDING"
    CLEAN = "CLEAN"
    INFECTED = "INFECTED"
    SKIPPED = "SKIPPED"


# Which documents each customer type must supply (spec §18.5).
REQUIRED_DOCUMENTS: dict[CustomerType, tuple[KycDocumentType, ...]] = {
    CustomerType.RETAIL: (KycDocumentType.AADHAAR, KycDocumentType.PAN),
    CustomerType.INDUSTRIAL: (KycDocumentType.FSSAI, KycDocumentType.GST),
}

# --- Account status: backend word -> mobile word (spec §2 CustomerAccountStatus) -----------
# NEW is not a stored status; it is the absence of a profile, which the mappers handle.
ACCOUNT_STATUS_TO_MOBILE: dict[str, str] = {
    CUSTOMER_PROFILE_INCOMPLETE: "NEW",
    CUSTOMER_DOCUMENTS_PENDING: "NEW",
    CUSTOMER_UNDER_REVIEW: "PENDING",
    CUSTOMER_APPROVED: "APPROVED",
    CUSTOMER_REJECTED: "REJECTED",
    CUSTOMER_SUSPENDED: "SUSPENDED",
}

# The reverse direction is only needed for list filters, where several backend statuses can
# collapse onto one mobile word — so it maps to a set, not a single value.
MOBILE_TO_ACCOUNT_STATUSES: dict[str, tuple[str, ...]] = {
    "NEW": (CUSTOMER_PROFILE_INCOMPLETE, CUSTOMER_DOCUMENTS_PENDING),
    "PENDING": (CUSTOMER_UNDER_REVIEW,),
    "APPROVED": (CUSTOMER_APPROVED,),
    "REJECTED": (CUSTOMER_REJECTED,),
    "SUSPENDED": (CUSTOMER_SUSPENDED,),
}

# Allowed account-status moves. Every write goes through StatusMachine with this table, so a
# client-supplied status can never drive a transition that is not listed.
ACCOUNT_TRANSITIONS: dict[str, set[str]] = {
    CUSTOMER_PROFILE_INCOMPLETE: {CUSTOMER_UNDER_REVIEW},
    CUSTOMER_DOCUMENTS_PENDING: {CUSTOMER_UNDER_REVIEW},
    CUSTOMER_UNDER_REVIEW: {CUSTOMER_APPROVED, CUSTOMER_REJECTED},
    # Resubmission after a rejection: the SRS allows the customer to correct and submit again.
    CUSTOMER_REJECTED: {CUSTOMER_UNDER_REVIEW},
    CUSTOMER_APPROVED: {CUSTOMER_SUSPENDED},
    CUSTOMER_SUSPENDED: {CUSTOMER_APPROVED},
}

APPLICATION_TRANSITIONS: dict[str, set[str]] = {
    ApplicationStatus.PENDING: {ApplicationStatus.APPROVED, ApplicationStatus.REJECTED},
    ApplicationStatus.APPROVED: set(),
    ApplicationStatus.REJECTED: set(),
}

EDITABLE_ACCOUNT_STATUSES = {CUSTOMER_PROFILE_INCOMPLETE, CUSTOMER_DOCUMENTS_PENDING, CUSTOMER_REJECTED}


def to_mobile_account_status(value: str | None) -> str:
    """The word the apps route on. A customer with no profile row is `NEW`."""
    if value is None:
        return "NEW"
    return ACCOUNT_STATUS_TO_MOBILE.get(value, value)
