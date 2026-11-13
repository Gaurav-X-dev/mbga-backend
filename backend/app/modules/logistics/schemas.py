from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Priority(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,29}$")
    label: str = Field(min_length=1, max_length=40)
    rank: int = Field(ge=0, le=100)
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class Coordinate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class LogisticsPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    priorities: list[Priority] = Field(min_length=1, max_length=12)
    defaultOrigin: Coordinate | None = None
    defaultDestination: Coordinate | None = None
    defaultPriority: str
    maxStops: int = Field(ge=1, le=25)
    optimizationEnabled: bool = False
    priorityFirst: bool = True
    requireSeparateReturnVerifier: bool = True
    requireOdometer: bool = False
    maxLoadCylinders: int = Field(ge=1, le=100000)

    @model_validator(mode="after")
    def unique_codes(self):
        codes = [p.code for p in self.priorities]
        if len(codes) != len(set(codes)) or self.defaultPriority not in codes:
            raise ValueError("Priority codes must be unique and include the default priority.")
        return self


Identifier = Annotated[str, Field(min_length=1, max_length=36)]


class TripCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    deliveryIds: list[Identifier] = Field(min_length=1, max_length=25)
    origin: Coordinate | None = None
    destination: Coordinate | None = None
    idempotencyKey: str = Field(min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


class Versioned(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expectedVersion: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=3, max_length=2000)


class StopCoordinate(Coordinate):
    deliveryId: Identifier


class SequenceUpdate(Versioned):
    coordinates: list[StopCoordinate] = Field(default_factory=list, max_length=25)
    deliveryIds: list[Identifier] = Field(min_length=1, max_length=25)
    pinnedDeliveryIds: list[Identifier] = Field(default_factory=list, max_length=25)


class LoadLine(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    cylinderType: str = Field(min_length=1, max_length=40)
    loadedFilled: int = Field(ge=0, le=100000, strict=True)
    openingEmpty: int = Field(default=0, ge=0, le=100000, strict=True)


class TripAction(Versioned):
    confirmedUnloaded: bool = Field(default=False, strict=True)
    action: Literal["READY", "DRAFT", "START", "RETURN", "VERIFY", "RESOLVE", "CANCEL"]
    loads: list[LoadLine] | None = Field(default=None, max_length=50)
    counts: list["ReturnLine"] | None = Field(default=None, max_length=50)
    odometer: int | None = Field(default=None, ge=0, le=100000000, strict=True)


class ReturnLine(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    cylinderType: str = Field(min_length=1, max_length=40)
    filled: int = Field(ge=0, le=100000, strict=True)
    empty: int = Field(ge=0, le=100000, strict=True)
    damaged: int = Field(default=0, ge=0, le=100000, strict=True)


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: LogisticsPolicy | None


TripAction.model_rebuild()
