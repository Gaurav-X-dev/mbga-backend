"""Pydantic schemas for the Orders domain (API Reference §6)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class OrderStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class OrderItemKind(StrEnum):
    CYLINDER_DELIVERY = "cylinderDelivery"
    EMPTY_COLLECTION = "emptyCollection"


class HistoryPeriod(StrEnum):
    TODAY = "today"
    WEEK = "week"
    ALL = "all"


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class OrderItemResponse(BaseModel):
    id: str
    kind: str
    label: str
    quantity: int


class OrderResponse(BaseModel):
    id: str
    orderNumber: str
    customerName: str
    customerPhone: str
    address: str
    timeSlotStart: str | None = None
    timeSlotEnd: str | None = None
    status: str
    distanceKm: float | None = None
    completedAt: str | None = None
    items: list[OrderItemResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Query-param schemas
# ---------------------------------------------------------------------------

class OrderListParams(BaseModel):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)
    status: OrderStatus | None = None


class OrderHistoryParams(BaseModel):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)
    status: OrderStatus | None = None
    period: HistoryPeriod | None = None
