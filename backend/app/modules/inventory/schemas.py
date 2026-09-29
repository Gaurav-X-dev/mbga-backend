"""Request and response models for the warehouse screens (spec §3.13, §11).

Field names are the mobile contract's camelCase. Counts are plain integers, so no Decimal
serializer is needed here - a cylinder is a whole thing.

Timestamps go out as UTC with a `Z`, for the same reason as orders: MySQL DATETIME keeps no
offset, and a naive string is read by JS as local time, which would date every movement five
and a half hours out.

Field-level rules live in `validation.py` rather than in Pydantic constraints, because which
fields are required depends on `type` - a correction needs `newCount` and no `quantity`, a
refill the reverse - and because a failure has to come back as the coded envelope the apps
read rather than FastAPI's list-shaped 422.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    model_serializer,
    model_validator,
)

from app.modules.inventory.constants import (
    MovementReference,
    StockBucket,
    StockMovementType,
)
from app.modules.notifications.constants import Severity
from app.modules.pricing.constants import CylinderType
from app.shared.exceptions.api_error import ApiError

_CAMEL = ConfigDict(populate_by_name=True, serialize_by_alias=True)


def _as_utc(value: datetime) -> str:
    moment = value if value.tzinfo else value.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


UtcTime = Annotated[datetime, PlainSerializer(_as_utc, return_type=str, when_used="json-unless-none")]


# --- Snapshot -------------------------------------------------------------------------------


class StockItemResponse(BaseModel):
    """Spec §3.13 `StockItem`. One card on the Warehouse Stock screen."""

    cylinder_type: CylinderType = Field(alias="cylinderType")
    cylinder_label: str = Field(alias="cylinderLabel")
    filled: int
    empty: int
    damaged: int
    reorder_threshold: int = Field(alias="reorderThreshold")
    # Null for a type this merchant has never stocked: there is no movement behind the zeros,
    # so claiming a moment at which they were counted would be a lie.
    updated_at: UtcTime | None = Field(default=None, alias="updatedAt")

    model_config = _CAMEL


class StockAlertResponse(BaseModel):
    """Spec §3.13 `StockAlert`. Derived from live counts, never stored."""

    id: str
    cylinder_type: CylinderType = Field(alias="cylinderType")
    severity: Severity
    # Rendered verbatim on the screen.
    message: str

    model_config = _CAMEL


class InventorySnapshotResponse(BaseModel):
    """Spec §11.1. Every cylinder type, always, so the screen's card grid never changes shape."""

    items: list[StockItemResponse]
    alerts: list[StockAlertResponse]
    as_of: UtcTime = Field(alias="asOf")

    model_config = _CAMEL


# --- The ledger -----------------------------------------------------------------------------


class MovementDeltas(BaseModel):
    """Signed bucket changes, e.g. `{"empty": -2, "damaged": 2}` (spec §3.13).

    Untouched buckets are omitted rather than sent as zero, matching the spec's payloads: a
    refill reads `{"filled": 60}`, not `{"filled": 60, "empty": 0, "damaged": 0}`.
    """

    filled: int | None = None
    empty: int | None = None
    damaged: int | None = None

    model_config = ConfigDict(serialize_by_alias=True)

    @model_serializer
    def _only_the_buckets_that_moved(self) -> dict[str, int]:
        """Drop the untouched buckets instead of sending them as null.

        `{"filled": 60, "empty": null, "damaged": null}` would make the app decide whether a
        null means "unchanged" or "unknown". Omitting them says it once: a bucket that is not
        here did not move.
        """
        moved = (("filled", self.filled), ("empty", self.empty), ("damaged", self.damaged))
        return {name: value for name, value in moved if value is not None}


class StockMovementResponse(BaseModel):
    """Spec §3.13 `StockMovement`. One row of the history."""

    id: str
    type: StockMovementType
    cylinder_type: CylinderType = Field(alias="cylinderType")
    cylinder_label: str = Field(alias="cylinderLabel")
    # Always positive; `deltas` carries the direction.
    quantity: int
    deltas: MovementDeltas
    note: str | None = None
    reference_type: MovementReference | None = Field(default=None, alias="referenceType")
    reference_id: str | None = Field(default=None, alias="referenceId")
    recorded_by: str | None = Field(default=None, alias="recordedBy")
    recorded_at: UtcTime = Field(alias="recordedAt")

    model_config = _CAMEL


class RecordStockMovementRequest(BaseModel):
    """Spec §11.3 `RecordStockMovementRequest`.

    Everything is optional at this layer on purpose. Which fields a body must carry depends
    on `type`, and Pydantic cannot express that without four separate models; `validation.py`
    applies the per-type rules and names the offending field the way the app expects.
    """

    type: StockMovementType
    cylinder_type: CylinderType = Field(alias="cylinderType")
    quantity: int | None = None
    from_bucket: StockBucket | None = Field(default=None, alias="fromBucket")
    bucket: StockBucket | None = None
    new_count: int | None = Field(default=None, alias="newCount")
    note: str | None = None
    reference_id: str | None = Field(default=None, alias="referenceId")

    model_config = _CAMEL

    @model_validator(mode="before")
    @classmethod
    def _counts_are_not_booleans(cls, data: object) -> object:
        """Refuse `true` where a count belongs, before it silently becomes 1.

        `bool` is a subclass of `int`, so Pydantic's lax mode accepts `"quantity": true` and
        hands `1` on. That has to be caught here rather than in `validation.py`: by the time
        the model exists the boolean is already an integer and the evidence is gone.

        Raised as the project's coded error rather than a `ValueError`, so a malformed body on
        this endpoint comes back in the same envelope as every other refusal - Pydantic's own
        failures render as FastAPI's list shape on non-auth paths, which the app does not read.
        """
        if not isinstance(data, dict):
            return data
        for key in ("quantity", "newCount", "new_count"):
            if isinstance(data.get(key), bool):
                raise ApiError(
                    "VALIDATION_ERROR",
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    fields=[
                        {
                            "field": "quantity" if key == "quantity" else "newCount",
                            "code": "not_an_integer",
                            "message": "Enter a whole number of cylinders",
                        }
                    ],
                )
        return data
