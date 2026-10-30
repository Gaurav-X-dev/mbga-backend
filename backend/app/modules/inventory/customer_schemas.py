"""Read-only customer inventory contract. Codes identify rows; labels are display-only."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.modules.payments.schemas import UtcTime


class View(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True
    )


class CylinderOption(View):
    code: str
    label: str
    variant: str | None = None
    is_eligible_for_ordering: bool
    historical_only: bool


class HoldingItem(View):
    cylinder_type: str
    cylinder_label: str
    variant: str | None = None
    is_eligible_for_ordering: bool
    historical_only: bool
    total_delivered: int
    total_returned: int
    current_holding: int


class InventoryResponse(View):
    as_of: UtcTime
    total_holding: int
    items: list[HoldingItem]


class Movement(View):
    id: str
    movement_type: Literal["DELIVERY", "RETURN"]
    occurred_at: UtcTime
    cylinder_type: str
    cylinder_label: str
    variant: str | None = None
    quantity: int
    holding_delta: int
    order_id: str
    order_number: str
    delivery_slip_id: str
    delivery_slip_number: str
    timestamp_source: Literal["DELIVERED_AT", "UPDATED_AT_FALLBACK"]


class Period(View):
    date_from: date | None
    date_to: date | None
    timezone: str = "Asia/Kolkata"


class MovementSummary(View):
    delivered_quantity: int
    returned_quantity: int
    net_movement: int


class Pagination(View):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool


class MovementsResponse(View):
    period: Period
    summary: MovementSummary
    items: list[Movement]
    pagination: Pagination


class MovementOption(View):
    code: Literal["DELIVERY", "RETURN"]
    label: str


class FiltersResponse(View):
    cylinder_types: list[CylinderOption]
    movement_types: list[MovementOption]
    variants: list[str]
    timezone: str = "Asia/Kolkata"
    default_page_size: int = 20
    max_page_size: int = 100
