"""Pydantic schemas for the Inventory domain (API Reference §10)."""

from __future__ import annotations

from pydantic import BaseModel


class DriverInventoryResponse(BaseModel):
    fullCylinderCount: int
    emptyCylinderCount: int
    vehicleCapacity: int
    lastUpdatedAt: str
