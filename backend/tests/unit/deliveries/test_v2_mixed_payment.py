import pytest
from pydantic import ValidationError

from app.modules.driver.v2_schemas import PaymentEntryV2, PaymentMethodV2
from app.modules.driver.v2_service import DriverV2Service
from app.shared.exceptions.api_error import ApiError


def payment(**overrides) -> PaymentEntryV2:
    values = {
        "method": "MIXED",
        "split": "full",
        "amountCollected": 1800,
        "cashAmount": 1000,
        "upiAmount": 800,
        "payableAmount": 1800,
        "pendingBalance": 0,
    }
    values.update(overrides)
    return PaymentEntryV2.model_validate(values)


def test_mixed_accepts_an_exact_positive_cash_and_upi_split() -> None:
    entry = payment()
    DriverV2Service._validate_breakdown(
        entry.method,
        round(entry.amount_collected),
        round(entry.cash_amount or 0),
        round(entry.upi_amount or 0),
    )


@pytest.mark.parametrize(
    ("cash", "upi"),
    [(1000, 799), (0, 1800), (1800, 0)],
)
def test_mixed_rejects_a_wrong_or_zero_portion(cash: int, upi: int) -> None:
    with pytest.raises(ApiError) as raised:
        DriverV2Service._validate_breakdown(PaymentMethodV2.MIXED, 1800, cash, upi)
    assert raised.value.status_code == 422
    assert raised.value.code == "PAYMENT_BREAKDOWN_INVALID"


def test_mixed_requires_both_breakdown_fields() -> None:
    with pytest.raises(ValidationError):
        payment(upiAmount=None)


def test_legacy_cash_and_upi_payloads_keep_working() -> None:
    common = {
        "split": "full",
        "amountCollected": 1800,
        "payableAmount": 1800,
        "pendingBalance": 0,
    }
    cash = PaymentEntryV2.model_validate({"method": "CASH", **common})
    upi = PaymentEntryV2.model_validate({"method": "UPI", **common})
    assert (cash.cash_amount, cash.upi_amount) == (1800, 0)
    assert (upi.cash_amount, upi.upi_amount) == (0, 1800)
