"""Whether a customer may place an order (spec §7.4, §18.2).

One policy, called by the eligibility endpoint today and by order creation when that slice
lands. Duplicating these rules in the order route is the failure this module exists to
prevent: the Create Order screen would grey out the form for the right reasons while the
backend accepted the order anyway.

Reasons are user-facing sentences, because the app renders them verbatim.
"""

from dataclasses import dataclass

from app.modules.authentication.account_state import (
    CUSTOMER_APPROVED,
    CUSTOMER_REJECTED,
    CUSTOMER_SUSPENDED,
    CUSTOMER_UNDER_REVIEW,
)
from app.modules.customers.constants import CustomerType, KycStatus
from app.modules.customers.models import CustomerDeliverySite, CustomerProfile


@dataclass(frozen=True)
class Eligibility:
    eligible: bool
    reasons: list[str]


ACCOUNT_REASONS = {
    CUSTOMER_UNDER_REVIEW: "Account is pending - only approved customers can order.",
    CUSTOMER_REJECTED: "This application was rejected.",
    CUSTOMER_SUSPENDED: "This account is suspended.",
}

KYC_REASONS = {
    KycStatus.NOT_SUBMITTED.value: "KYC documents have not been submitted.",
    KycStatus.PENDING.value: "KYC is not verified.",
    KycStatus.REJECTED.value: "KYC was rejected.",
}


def evaluate(profile: CustomerProfile, sites: list[CustomerDeliverySite]) -> Eligibility:
    """Collect **every** blocking reason, not just the first.

    The app shows the list, so a customer who is both unapproved and unverified should see
    both rather than fixing one and discovering the other.
    """
    reasons: list[str] = []
    if profile.status != CUSTOMER_APPROVED:
        reasons.append(ACCOUNT_REASONS.get(profile.status, "Account is pending - only approved customers can order."))
    if profile.kyc_status != KycStatus.VERIFIED.value:
        reasons.append(KYC_REASONS.get(profile.kyc_status, "KYC is not verified."))
    # Spec 18.2: an industrial order carries a delivery site, so a customer with none
    # cannot have an order placed for them even once approved.
    if profile.customer_type == CustomerType.INDUSTRIAL.value and not any(site.is_active for site in sites):
        reasons.append("Add a delivery site before placing an order.")
    return Eligibility(eligible=not reasons, reasons=reasons)
