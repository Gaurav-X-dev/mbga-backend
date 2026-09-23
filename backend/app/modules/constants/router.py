"""Reference data the apps fill their dropdowns from.

One public endpoint returning one flat list of `{key, value}` options, so the Customer and
Merchant apps stop shipping hard-coded lists. A merchant added in the database appears in the
app immediately, with no new release.

**Why some options come from the database and some from code.** Whatever answers here has to
be the same thing the write endpoints validate against, or the app will offer a choice the
backend then rejects. So each option is served from wherever its truth already lives:
merchants from the `merchants` table, and the fixed vocabularies from the enums the validators
themselves use. Moving those enums into a table would not make them more correct - it would
only create a second copy that can disagree with the code.

Public on purpose: a customer chooses their merchant *before* they have an account, so there
is no token to check. Only a display code and a name leave this endpoint - never an internal
id, a status, a count, or anything about another customer.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings, get_settings
from app.modules.authentication.audit import ClientInfo
from app.modules.authentication.dependencies import get_client_info
from app.modules.authentication.throttle import RequestThrottle
from app.modules.customers.constants import CustomerType, KycDocumentType, PricingTier
from app.modules.merchants.models import Merchant
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.exceptions.openapi import error_responses

router = APIRouter(tags=["Constants"])

# The states the business currently delivers in. Not a database table because nothing in the
# system is keyed by state; it is a spelling aid for the address form.
DELIVERY_STATES = ("Madhya Pradesh", "Maharashtra", "Rajasthan", "Gujarat", "Uttar Pradesh", "Chhattisgarh")

# Human labels for the fixed vocabularies. The key is what the app sends back to the API.
CUSTOMER_TYPE_LABELS = {CustomerType.RETAIL: "Retail", CustomerType.INDUSTRIAL: "Industrial"}
DOCUMENT_TYPE_LABELS = {
    KycDocumentType.AADHAAR: "Aadhaar Card",
    KycDocumentType.PAN: "PAN Card",
    KycDocumentType.FSSAI: "FSSAI Licence",
    KycDocumentType.GST: "GST Certificate",
}
PRICING_TIER_LABELS = {
    PricingTier.STANDARD: "Standard",
    PricingTier.BULK: "Bulk",
    PricingTier.KEY_ACCOUNT: "Key Account",
}

# What `?type=` accepts. Everything is returned when it is omitted.
MERCHANTS = "merchants"
CUSTOMER_TYPES = "customerTypes"
DOCUMENT_TYPES = "documentTypes"
PRICING_TIERS = "pricingTiers"
STATES = "states"
TYPES = (MERCHANTS, CUSTOMER_TYPES, DOCUMENT_TYPES, PRICING_TIERS, STATES)


class Option(BaseModel):
    """One option. `key` is what the app sends back to the API, `value` is what it shows."""

    key: str
    value: str


def _options(labels: dict) -> list[Option]:
    return [Option(key=str(key), value=label) for key, label in labels.items()]


@router.get(
    "/constants",
    response_model=list[Option],
    responses=error_responses(422, 429),
    summary="Key/value options for both apps",
)
async def constants(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    client: Annotated[ClientInfo, Depends(get_client_info)],
    type: Annotated[
        str | None,
        Query(description="Return one set only: merchants, customerTypes, documentTypes, pricingTiers or states."),
    ] = None,
) -> list[Option]:
    """One flat list of `{key, value}`, ready to drop into any picker.

    Fetch it once at startup and cache it for the session. Pass `?type=merchants` when a
    screen needs a single set rather than the whole list - without it the app has no way to
    tell a merchant option from a customer-type option, because a flat list carries no
    grouping.
    """
    # Unauthenticated, so it is limited per client IP like the other public endpoints.
    try:
        await RequestThrottle(session, settings.jwt_signing_secret).hit(
            "constants:ip", client.ip_address, settings.constants_limit_per_ip
        )
    finally:
        await session.commit()

    wanted = (type or "").strip()
    if wanted and wanted not in TYPES:
        raise ApiError(
            "VALIDATION_ERROR",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            fields=[{"field": "type", "code": "invalid", "message": f"Use one of: {', '.join(TYPES)}."}],
        )

    options: list[Option] = []
    if not wanted or wanted == MERCHANTS:
        # Only merchants a customer could actually register under. A blocked or unapproved
        # merchant is absent rather than shown-and-rejected.
        merchants = await session.scalars(
            select(Merchant)
            .where(Merchant.status == "ACTIVE", Merchant.approval_status == "APPROVED")
            .order_by(Merchant.name)
        )
        # The display code, never Merchant.id: the code is what registration accepts, and the
        # internal id has no business leaving the backend.
        options += [Option(key=m.code, value=m.name) for m in merchants]
    if not wanted or wanted == CUSTOMER_TYPES:
        options += _options(CUSTOMER_TYPE_LABELS)
    if not wanted or wanted == DOCUMENT_TYPES:
        options += _options(DOCUMENT_TYPE_LABELS)
    if not wanted or wanted == PRICING_TIERS:
        options += _options(PRICING_TIER_LABELS)
    if not wanted or wanted == STATES:
        options += [Option(key=name, value=name) for name in DELIVERY_STATES]
    return options
