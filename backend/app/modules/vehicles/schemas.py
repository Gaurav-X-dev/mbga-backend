"""What the panel sends and reads for a van."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_CAMEL = ConfigDict(populate_by_name=True, from_attributes=True)


class VehicleCreate(BaseModel):
    #: Normalised on the way in - upper-cased, runs of spaces collapsed - so one van cannot be
    #: added twice under two spellings.
    number: str = Field(min_length=4, max_length=50)
    label: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=255)
    model_config = _CAMEL


class VehicleUpdate(BaseModel):
    number: str | None = Field(default=None, min_length=4, max_length=50)
    label: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=255)
    #: False retires the van. It stops being offered and keeps every slip that names it.
    is_active: bool | None = Field(default=None, alias="isActive")
    model_config = _CAMEL


class VehicleResponse(BaseModel):
    id: str
    number: str
    label: str | None = None
    notes: str | None = None
    is_active: bool = Field(alias="isActive")
    created_at: datetime = Field(alias="createdAt")
    model_config = _CAMEL


class VehicleListResponse(BaseModel):
    items: list[VehicleResponse]
    total: int


class VehiclePincodeReplaceRequest(BaseModel):
    pincodes: list[str] = Field(min_length=0, max_length=5000)
    model_config = _CAMEL


class VehiclePincodeResponse(BaseModel):
    vehicle_id: str = Field(alias="vehicleId")
    pincodes: list[str]
    model_config = _CAMEL


class AvailableVehicleResponse(VehicleResponse):
    priority: int = 0
    matched_pincode: str = Field(alias="matchedPincode")
    #: Who this van is already out with on the day being scheduled, or null when it is free.
    #:
    #: The rule is one van, one driver, one day - so a van already out is only a clash for a
    #: **different** driver; the same driver filling a round through the morning is the ordinary
    #: case and stays allowed. That is why a busy van is still listed: hiding it would block the
    #: assignment that is actually correct.
    #:
    #: The screen's job is to say so before the operator presses Confirm, rather than after.
    busy_with_driver_name: str | None = Field(default=None, alias="busyWithDriverName")
    busy_with_driver_user_id: str | None = Field(default=None, alias="busyWithDriverUserId")
