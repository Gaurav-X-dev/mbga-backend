"""Shared API contracts for customer trade-credit controls."""

from pydantic import BaseModel, ConfigDict, Field


class CustomerCreditUpdate(BaseModel):
    credit_enabled: bool = Field(alias="creditEnabled")
    credit_limit: int = Field(alias="creditLimit", ge=0)
    credit_days: int | None = Field(default=None, alias="creditDays", ge=1, le=365)
    reason: str = Field(min_length=5, max_length=500)

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

