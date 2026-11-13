from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FinancePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    advanceEnabled: bool = False
    autoUseAdvance: bool = True
    allowPartialAdvance: bool = True
    maxDepositAmount: int = Field(default=10000000, ge=1, le=100000000)
    handoverEnabled: bool = True
    requireSeparateVerifier: bool = False


class SettingsUpdate(BaseModel):
    config: FinancePolicy | None
    model_config = ConfigDict(extra="forbid")


class DepositInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    customerId: str | None = Field(default=None, max_length=36)
    amount: int = Field(gt=0, le=100000000, strict=True)
    mode: Literal["CASH", "UPI", "NEFT"]
    reference: str | None = Field(default=None, min_length=1, max_length=100)
    idempotencyKey: str = Field(min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def reference_required(self):
        if self.mode != "CASH" and not self.reference:
            raise ValueError("Bank/UPI reference is required. Funds remain pending until verified.")
        return self


class DepositVerification(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    verified: bool
    reason: str = Field(min_length=3, max_length=2000)


class RefundInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    customerId: str = Field(max_length=36)
    amount: int = Field(gt=0, le=100000000, strict=True)
    reference: str = Field(min_length=1, max_length=100)
    idempotencyKey: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=3, max_length=2000)


class HandoverInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    driverId: str | None = Field(default=None, max_length=36)
    paymentIds: list[str] = Field(min_length=1, max_length=200)
    idempotencyKey: str = Field(min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


class HandoverVerification(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    receivedAmount: int = Field(ge=0, le=100000000, strict=True)
    notes: str = Field(min_length=3, max_length=2000)
    reject: bool = False
