from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

CYLINDERS = {
    "5 kg": "LPG_5KG",
    "10 kg": "LPG_10KG",
    "19 kg": "LPG_19KG",
    "47.5 kg": "LPG_47_5KG_L",
    "422 kg": "LPG_422KG_HIPPO",
}
CYLINDERS.update({"47.5 kg (LOT)": "LPG_47_5KG_L", "47.5 kg (VOT)": "LPG_47_5KG_V"})
LABELS = {v: k for k, v in CYLINDERS.items()}


def cylinder(value: str) -> str:
    value = CYLINDERS.get(value, value)
    if value not in LABELS:
        raise ValueError("Unsupported cylinderType")
    return value


def customer(value: str) -> str:
    aliases = {"Retail": "Retail (Domestic)", "Commercial": "Commercial (Industrial)"}
    value = aliases.get(value, aliases.get(value.title(), value))
    if value not in ("Retail (Domestic)", "Commercial (Industrial)"):
        raise ValueError("Unsupported customerType")
    return value


Pincode = Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{5}$")]
Money = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2, allow_inf_nan=False)]


class Request(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True, str_strip_whitespace=True, validate_default=True
    )


class DepotAddress(Request):
    line1: str | None = Field(default=None, max_length=255)
    line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    pincode: Pincode | None = None
    latitude: Decimal | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)

    @model_validator(mode="after")
    def paired_coordinates(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Provide both latitude and longitude.")
        return self


class BrandRequest(Request):
    name: str = Field(min_length=1, max_length=160)
    notes: str | None = Field(default=None, max_length=4000)
    color: str = Field(default="#8B5CF6", pattern=r"^#[0-9a-fA-F]{6}$")
    icon_name: str = Field(default="storefront-outline", alias="iconName", max_length=60)
    depot_address: DepotAddress | None = Field(default=None, alias="depotAddress")


class BrandStatus(Request):
    status: Literal["ACTIVE", "INACTIVE"] | None = None
    notes: str | None = Field(default=None, max_length=4000)
    depot_address: DepotAddress | None = Field(default=None, alias="depotAddress")

    @model_validator(mode="after")
    def has_update(self):
        if not self.model_fields_set:
            raise ValueError("Provide status, notes or depotAddress.")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("Status cannot be null.")
        return self


class BaseRateRequest(Request):
    cylinder_type: str = Field(alias="cylinderType")
    price: Money
    notes: str | None = Field(default=None, max_length=4000)
    _cylinder = field_validator("cylinder_type")(cylinder)


class PriceRequest(BaseRateRequest):
    competitor_id: str = Field(alias="competitorId", min_length=1, max_length=36)
    customer_type: str = Field(alias="customerType")
    location_pincode: Pincode = Field(alias="locationPincode")
    effective_date: date = Field(alias="effectiveDate")
    _customer = field_validator("customer_type")(customer)


class Filters(Request):
    cylinder_type: str = Field(default="19 kg", alias="cylinderType")
    customer_type: str = Field(default="Retail (Domestic)", alias="customerType")
    pincode: Pincode | Literal["ALL"] | None = None
    all_pincodes: bool = Field(default=False, alias="allPincodes")
    _cylinder = field_validator("cylinder_type", mode="before")(cylinder)
    _customer = field_validator("customer_type")(customer)


class ConsolidatedExport(Request):
    format: str = "XLSX"
    pincode: Pincode | Literal["ALL"] | None = None
    all_pincodes: bool = Field(default=False, alias="allPincodes")
    cylinder_types: list[str] = Field(
        default_factory=lambda: list(LABELS), alias="cylinderTypes", min_length=1, max_length=6
    )
    customer_type: str = Field(default="Retail (Domestic)", alias="customerType")
    timeframe: Literal["7D", "30D", "3M", "1Y", "CUSTOM"] | None = None
    start_date: date | None = Field(default=None, alias="startDate")
    end_date: date | None = Field(default=None, alias="endDate")
    include_audit: bool = Field(default=False, alias="includeAudit")
    _customer = field_validator("customer_type")(customer)

    @field_validator("format")
    @classmethod
    def valid_format(cls, value):
        if value.upper() not in {"XLSX", "CSV"}:
            raise ValueError("format must be XLSX or CSV")
        return value.upper()

    @field_validator("cylinder_types")
    @classmethod
    def valid_cylinders(cls, values):
        result = [cylinder(value) for value in values]
        if len(set(result)) != len(result):
            raise ValueError("Duplicate cylinderTypes are not allowed")
        return result
