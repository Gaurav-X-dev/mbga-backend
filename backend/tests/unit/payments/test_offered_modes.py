"""Which modes money may be taken in, and why the enum is not the answer.

The agency takes cash at the gate and UPI through the QR. A bank transfer is arranged with the
office, never handed to a driver, so offering NEFT put a choice on the app that nobody could
complete and in a dropdown the merchant panel had no use for.

Withdrawing it is not the same as deleting it. `PaymentMode` still has `NEFT` so that a payment
recorded in it months ago keeps reading back - a row is a record of what happened, and records
do not change when a policy does.
"""

import pytest

from app.modules.payments import validation
from app.modules.payments.constants import OFFERED_PAYMENT_MODES, PaymentMode
from app.shared.exceptions.api_error import ApiError

pytestmark = [pytest.mark.unit]


def test_cash_and_upi_are_what_is_taken():
    assert OFFERED_PAYMENT_MODES == {PaymentMode.CASH, PaymentMode.UPI}


def test_a_withdrawn_mode_is_still_a_mode():
    """So an old NEFT payment still loads instead of raising on the way out of the database."""
    assert PaymentMode("NEFT") is PaymentMode.NEFT


@pytest.mark.parametrize("mode", sorted(OFFERED_PAYMENT_MODES))
def test_an_offered_mode_passes(mode):
    assert validation.check_mode(mode) is mode


def test_a_withdrawn_mode_cannot_be_recorded():
    """The dropdown is a suggestion; this is the rule."""
    with pytest.raises(ApiError) as raised:
        validation.check_mode(PaymentMode.NEFT)

    assert raised.value.status_code == 422
    assert raised.value.detail["fields"][0]["code"] == "mode_not_offered"


def test_the_dropdown_offers_exactly_what_may_be_recorded():
    """An option the backend would refuse is worse than no option at all."""
    from app.modules.constants.seeds import PAYMENT_MODES, seed_rows

    offered = {row.key for row in seed_rows() if row.group == PAYMENT_MODES}
    assert offered == {mode.value for mode in OFFERED_PAYMENT_MODES}
