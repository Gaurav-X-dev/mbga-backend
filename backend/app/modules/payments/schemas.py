"""Pydantic schemas for the Payments domain (API Reference §11)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PaymentMethodResponse(BaseModel):
    id: str
    type: str  # upi | card | cash | wallet
    label: str
    isDefault: bool


class PaymentTransactionResponse(BaseModel):
    id: str
    amount: float
    status: str  # pending | completed | failed
    createdAt: str


class PaymentHistoryParams(BaseModel):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)
