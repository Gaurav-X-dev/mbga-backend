"""The agency's UPI details, which decide whether a driver can take money at the gate.

Until now these two columns existed on the merchant row and nothing in the platform could
write them: not the create call, not the update call, and not the panel. A new agency was
created with them empty, the driver app answered `MERCHANT_UPI_NOT_CONFIGURED` for every QR,
and the only cure was somebody running SQL against production.

Two rules are worth pinning. A malformed VPA must be refused here rather than at the
customer's phone, and half a configuration must be refused outright - because half behaves
exactly like none, while looking like a saved setting.
"""

import pytest
from pydantic import ValidationError

from app.modules.merchants.schemas import MerchantCreate, MerchantUpdate

pytestmark = [pytest.mark.unit]


def create(**overrides):
    base = {
        "merchant_code": "MBGA01",
        "business_name": "Madhav Bharat Gas Agency",
        "contact_person_name": "Gaurav",
        "mobile_number": "9876543210",
    }
    base.update(overrides)
    return MerchantCreate(**base)


class TestTheAddressIsChecked:
    @pytest.mark.parametrize(
        "value",
        ["madhavgas@okhdfcbank", "9876543210@ybl", "madhav.gas-1@paytm", "a1@sbi"],
    )
    def test_a_real_looking_vpa_is_accepted(self, value):
        assert create(upi_id=value).upi_id == value

    @pytest.mark.parametrize(
        "value",
        [
            "madhavgas",          # no handle at all
            "@okhdfcbank",        # no name
            "madhavgas@",         # no bank
            "a@b",                # too short either side
            "madhav gas@ybl",     # a space, which NPCI refuses
            "madhav@@ybl",
        ],
    )
    def test_a_malformed_vpa_is_refused(self, value):
        # Refused here on purpose. A bad VPA still renders a QR, and the failure surfaces on
        # the customer's phone with the driver standing there.
        with pytest.raises(ValidationError, match="name@bank"):
            create(upi_id=value)

    def test_case_and_spacing_are_settled_once(self):
        # UPI handles are not case-sensitive, so two spellings of one address must not read
        # as two different addresses.
        assert create(upi_id="  MadhavGas@OkHdfcBank  ").upi_id == "madhavgas@okhdfcbank"

    def test_an_empty_string_is_the_same_as_unset(self):
        assert create(upi_id="   ").upi_id is None

    def test_the_payee_name_is_trimmed(self):
        assert create(upi_payee_name="  Madhav Bharat Gas  ").upi_payee_name == "Madhav Bharat Gas"


class TestUpdate:
    def test_both_fields_can_be_changed(self):
        payload = MerchantUpdate(upi_id="madhavgas@ybl", upi_payee_name="Madhav Bharat Gas")
        assert payload.upi_id == "madhavgas@ybl"
        assert payload.upi_payee_name == "Madhav Bharat Gas"

    def test_a_malformed_vpa_is_refused_on_update_too(self):
        with pytest.raises(ValidationError, match="name@bank"):
            MerchantUpdate(upi_id="not-a-vpa")

    def test_an_update_that_names_neither_leaves_both_alone(self):
        # `exclude_unset` is what the handler applies, so a field nobody sent must not appear
        # in it - otherwise saving the address form would wipe the UPI details.
        sent = MerchantUpdate(city="Indore").model_dump(exclude_unset=True)
        assert sent == {"city": "Indore"}
        assert "upi_id" not in sent and "upi_payee_name" not in sent
