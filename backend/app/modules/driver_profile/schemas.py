"""Pydantic schemas for the Driver Profile domain (API Reference §8)."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# §8.1 — Profile Response
# ---------------------------------------------------------------------------

class DriverProfileResponse(BaseModel):
    id: str
    name: str
    phone: str
    vehicleNumber: str | None = None
    role: str = "Driver"
    onDuty: bool = False
    avatarInitials: str | None = None


# ---------------------------------------------------------------------------
# §8.2 — Update On-Duty Status
# ---------------------------------------------------------------------------

class UpdateStatusRequest(BaseModel):
    onDuty: bool


# ---------------------------------------------------------------------------
# §8.3 — Update Language
# ---------------------------------------------------------------------------

class UpdateLanguageRequest(BaseModel):
    languageCode: str = Field(min_length=2, max_length=5)


class UpdateLanguageResponse(BaseModel):
    languageCode: str
