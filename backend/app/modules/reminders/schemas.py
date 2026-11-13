from datetime import datetime
from string import Formatter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Kind = Literal["PROXIMITY", "INACTIVE", "PRICING"]
PLACEHOLDERS = {"customer_name", "merchant_name", "days", "distance_km", "month", "reason"}


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    enabled: bool = False
    allowMerchantOverride: bool = False
    days: int = Field(default=30, ge=0, le=3650)
    radiusMeters: int = Field(default=5000, ge=1, le=100000)
    maxLocationAgeSeconds: int = Field(default=300, ge=10, le=3600)
    maxAccuracyMeters: int = Field(default=100, ge=1, le=5000)
    intervalHours: int = Field(default=24, ge=1, le=8760)
    maxCount: int = Field(default=3, ge=1, le=100)
    maxSnoozeHours: int = Field(default=168, ge=1, le=8760)
    notificationTtlHours: int = Field(default=24, ge=1, le=168)
    weekdays: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    startHour: int = Field(default=8, ge=0, le=23)
    endHour: int = Field(default=21, ge=0, le=23)
    pushEnabled: bool = True
    includeNeverOrdered: bool = False
    suppressActiveOrders: bool = True
    customerTypes: list[str] = Field(default_factory=list, max_length=100)
    groupIds: list[str] = Field(default_factory=list, max_length=100)
    staffUserIds: list[str] = Field(default_factory=list, max_length=100)
    upcomingDays: int = Field(default=3, ge=0, le=28)
    missingRates: bool = True
    staleReview: bool = True
    title: str = Field(default="Follow-up reminder", min_length=1, max_length=180)
    staffTemplate: str = Field(default="{customer_name}: {reason}", min_length=1, max_length=2000)
    customerTemplate: str = Field(
        default="Hello {customer_name}, ready for your next refill? Open the app to order.",
        min_length=1,
        max_length=2000,
    )

    @model_validator(mode="after")
    def validate_rule(self):
        if len(set(self.weekdays)) != len(self.weekdays) or any(
            day not in range(7) for day in self.weekdays
        ):
            raise ValueError("Choose unique weekdays from 0 (Monday) to 6 (Sunday).")
        if self.startHour == self.endHour:
            raise ValueError("Start and end hours must differ.")
        for text in (self.title, self.staffTemplate, self.customerTemplate):
            for _, name, spec, conversion in Formatter().parse(text):
                if name is not None and (name not in PLACEHOLDERS or spec or conversion):
                    raise ValueError("Templates support only simple approved placeholders.")
        return self


class PolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: Rule | None  # null resets a merchant override


class ReminderAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ACKNOWLEDGED", "SNOOZED", "RESOLVED"]
    snoozeHours: int | None = Field(default=None, ge=1)
    note: str | None = Field(default=None, max_length=1000)


class VisitInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    customerId: str = Field(max_length=36)
    siteId: str | None = Field(default=None, max_length=36)
    idempotencyKey: str = Field(min_length=1, max_length=100)
    outcome: Literal["VISITED", "UNAVAILABLE", "FOLLOW_UP", "CANCELLED"]
    notes: str | None = Field(default=None, max_length=4000)
    visitedAt: datetime
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0, le=100000)

    @model_validator(mode="after")
    def coordinates(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Provide both coordinates or neither.")
        if self.visitedAt.tzinfo is None:
            raise ValueError("Visit time requires a timezone.")
        return self


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    note: str | None = Field(default=None, max_length=2000)
