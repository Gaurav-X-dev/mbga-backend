"""Request and response models for the pricing screens.

Field names are the merchant app's (`PriceEntry`, `PricingMonth`, `CustomerPriceItem` in
`shared/types/order.ts`), so swapping the mocked `pricingService` for `apiClient` calls is a
drop-in. The snake_case columns stay in `models.py`; the translation is the aliases here.

Amounts are declared as `Decimal` and range-checked in the service rather than by Pydantic
constraints. A Pydantic failure on a merchant route returns FastAPI's list-shaped 422, which
the web panel maps to form fields; the service raises the coded `VALIDATION_ERROR` envelope
instead, which is what the spec's error contract describes.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.modules.pricing.constants import CylinderType, PricingMonthStatus, PricingTier

_CAMEL = ConfigDict(populate_by_name=True, serialize_by_alias=True)


def _as_number(value: Decimal) -> float:
    """Amounts go out as JSON numbers, not strings.

    Pydantic renders a `Decimal` as a quoted string by default, which the app's `number`
    fields (`PriceEntry.bpclBaseRate` and friends) would take as text - every total built
    from it would concatenate instead of adding. Decimal is still what the service and the
    columns use; only the wire form changes.
    """
    return float(value)


def _as_utc(value: datetime) -> str:
    """Timestamps go out as UTC with a `Z`, per the spec's `2026-09-14T18:05:00Z`.

    MySQL DATETIME keeps no offset, so a stored instant reads back naive. Everything here
    is written with `datetime.now(UTC)`, so a naive value *is* UTC and is labelled as such.
    Without the marker the app would read it as local time and show every price change
    five and a half hours out.
    """
    moment = value if value.tzinfo else value.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


Money = Annotated[Decimal, PlainSerializer(_as_number, return_type=float, when_used="json-unless-none")]
UtcTime = Annotated[datetime, PlainSerializer(_as_utc, return_type=str, when_used="json-unless-none")]


class PriceEntryResponse(BaseModel):
    """One rate in a month. `customerPrice` is server-computed and read-only."""

    cylinder_type: CylinderType = Field(alias="cylinderType")
    tier: PricingTier
    bpcl_base_rate: Money = Field(alias="bpclBaseRate")
    tier_markup: Money = Field(alias="tierMarkup")
    customer_price: Money = Field(alias="customerPrice")

    model_config = _CAMEL


class PricingMonthResponse(BaseModel):
    id: str
    month: str
    label: str
    effective_from: date = Field(alias="effectiveFrom")
    effective_to: date = Field(alias="effectiveTo")
    status: PricingMonthStatus
    gst_percent: Money = Field(alias="gstPercent")
    entries: list[PriceEntryResponse] = Field(default_factory=list)
    updated_by: str = Field(alias="updatedBy")
    updated_at: UtcTime = Field(alias="updatedAt")

    model_config = _CAMEL


class UpdatePriceEntryRequest(BaseModel):
    """A mid-month rate change. `customerPrice` is deliberately absent - it is derived."""

    cylinder_type: CylinderType = Field(alias="cylinderType")
    # Only STANDARD is populated today, so an omitted tier means the tab the app is on.
    tier: PricingTier = Field(default=PricingTier.STANDARD)
    bpcl_base_rate: Money = Field(alias="bpclBaseRate")
    tier_markup: Money = Field(alias="tierMarkup")
    # Defaults to the server's business date when omitted.
    effective_from: date | None = Field(default=None, alias="effectiveFrom")
    reason: str | None = Field(default=None, max_length=500)

    model_config = _CAMEL


class ChangedBy(BaseModel):
    """The acting user, taken from the session - never from the request body."""

    id: str
    name: str
    role: str


class PricingChangeLogItem(BaseModel):
    id: str
    pricing_month_id: str = Field(alias="pricingMonthId")
    cylinder_type: str = Field(alias="cylinderType")
    tier: str
    old_bpcl_base_rate: Money | None = Field(default=None, alias="oldBpclBaseRate")
    old_tier_markup: Money | None = Field(default=None, alias="oldTierMarkup")
    old_customer_price: Money | None = Field(default=None, alias="oldCustomerPrice")
    new_bpcl_base_rate: Money = Field(alias="newBpclBaseRate")
    new_tier_markup: Money = Field(alias="newTierMarkup")
    new_customer_price: Money = Field(alias="newCustomerPrice")
    effective_from: date = Field(alias="effectiveFrom")
    reason: str | None = None
    changed_by: ChangedBy = Field(alias="changedBy")
    changed_at: UtcTime = Field(alias="changedAt")

    model_config = _CAMEL


class PricingChangeLogPage(BaseModel):
    """Paged as the spec documents it (`page`/`pageSize`).

    The rest of the API pages with `limit`/`offset`; this endpoint keeps the shape its own
    contract names, and accepts `limit`/`offset` as well so a caller using the house style
    is not surprised. All four keys are returned either way.
    """

    items: list[PricingChangeLogItem]
    page: int
    page_size: int = Field(alias="pageSize")
    total: int
    limit: int
    offset: int

    model_config = _CAMEL


class CustomerPriceOverrideResponse(BaseModel):
    override_price: Money = Field(alias="overridePrice")
    effective_from: date = Field(alias="effectiveFrom")
    reason: str | None = None
    set_by: str = Field(alias="setBy")
    set_at: UtcTime = Field(alias="setAt")

    model_config = _CAMEL


class CustomerPriceItem(BaseModel):
    """One cylinder type as the Price Setting tab shows it.

    `effectivePrice` is what the customer actually pays: the override when one exists, the
    tier price otherwise. It is computed by the same helper order quoting will call, so the
    number on this screen is the number that will be billed.
    """

    cylinder_type: CylinderType = Field(alias="cylinderType")
    cylinder_label: str = Field(alias="cylinderLabel")
    tier_price: Money | None = Field(alias="tierPrice")
    override: CustomerPriceOverrideResponse | None = None
    effective_price: Money | None = Field(alias="effectivePrice")

    model_config = _CAMEL


class CustomerPricingResponse(BaseModel):
    customer_id: str = Field(alias="customerId")
    tier: str
    items: list[CustomerPriceItem] = Field(default_factory=list)

    model_config = _CAMEL


class SetCustomerPriceOverrideRequest(BaseModel):
    override_price: Money = Field(alias="overridePrice")
    effective_from: date | None = Field(default=None, alias="effectiveFrom")
    reason: str | None = Field(default=None, max_length=500)

    model_config = _CAMEL
