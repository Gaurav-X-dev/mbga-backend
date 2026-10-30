"""An agency's payment details: the UPI a driver collects on, and the bank an invoice names.

Six columns existed on the merchant row and nothing in the platform could write them. Not
create, not update, not the panel. A new agency was created with all six empty, the driver
app answered `MERCHANT_UPI_NOT_CONFIGURED` for every QR, invoices printed with no bank
details on them, and the only cure was SQL against production.

The UPI pair is required when an agency is created: one without it cannot take a rupee at the
gate, so allowing the creation only moves the discovery to a doorstep. The bank details stay
optional - an agency that takes no transfers does not need them, and an invoice without them
is still a valid invoice.
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
        "upi_id": "madhavgas@okhdfcbank",
        "upi_payee_name": "Madhav Bharat Gas Agency",
    }
    base.update(overrides)
    return MerchantCreate(**base)


class TestTheUpiPairIsRequiredToCreate:
    def test_an_agency_cannot_be_created_without_a_upi_id(self):
        with pytest.raises(ValidationError):
            MerchantCreate(
                merchant_code="MBGA01",
                business_name="Madhav Bharat Gas Agency",
                contact_person_name="Gaurav",
                mobile_number="9876543210",
                upi_payee_name="Madhav Bharat Gas Agency",
            )

    def test_an_agency_cannot_be_created_without_a_payee_name(self):
        with pytest.raises(ValidationError):
            MerchantCreate(
                merchant_code="MBGA01",
                business_name="Madhav Bharat Gas Agency",
                contact_person_name="Gaurav",
                mobile_number="9876543210",
                upi_id="madhavgas@okhdfcbank",
            )

    def test_a_blank_payee_name_is_not_a_payee_name(self):
        with pytest.raises(ValidationError, match="payment app should show"):
            create(upi_payee_name="   ")


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

    def test_the_payee_name_is_trimmed(self):
        assert create(upi_payee_name="  Madhav Bharat Gas  ").upi_payee_name == "Madhav Bharat Gas"


class TestBankDetails:
    def test_they_are_optional(self):
        # An agency that takes no transfers needs none of this, and an invoice without bank
        # details is still a valid invoice.
        merchant = create()
        assert merchant.invoice_bank_ifsc is None
        assert merchant.invoice_bank_account_number is None

    @pytest.mark.parametrize("value", ["HDFC0001234", "SBIN0012345", "icic0000456"])
    def test_a_real_looking_ifsc_is_accepted_and_upper_cased(self, value):
        assert create(invoice_bank_ifsc=value).invoice_bank_ifsc == value.upper()

    @pytest.mark.parametrize(
        "value",
        [
            "HDFC1001234",   # the fifth character must be a zero
            "HD0001234",     # too few letters
            "HDFC000123",    # too short
            "HDFC00012345",  # too long
        ],
    )
    def test_a_malformed_ifsc_is_refused(self, value):
        # A wrong IFSC does not fail at the panel; it fails days later when the transfer
        # bounces, by which time nobody connects it to this screen.
        with pytest.raises(ValidationError, match="HDFC0001234"):
            create(invoice_bank_ifsc=value)

    def test_spaces_in_an_account_number_are_dropped(self):
        # Account numbers are read off passbooks and pasted in groups of four.
        assert create(invoice_bank_account_number="5010 0123 4567").invoice_bank_account_number == "501001234567"

    @pytest.mark.parametrize("value", ["12345", "50100123456789012345678", "5010-0123"])
    def test_an_implausible_account_number_is_refused(self, value):
        with pytest.raises(ValidationError, match="6 to 20"):
            create(invoice_bank_account_number=value)


class TestUpdate:
    def test_every_field_stays_optional_on_update(self):
        # The panel sends only what changed, so a required field here would make editing the
        # address of a merchant with no UPI impossible.
        payload = MerchantUpdate(city="Indore")
        sent = payload.model_dump(exclude_unset=True)
        assert sent == {"city": "Indore"}

    def test_both_payment_blocks_can_be_changed(self):
        payload = MerchantUpdate(
            upi_id="MadhavGas@Ybl",
            upi_payee_name="Madhav Bharat Gas",
            invoice_bank_name="HDFC Bank",
            invoice_bank_account_name="Madhav Bharat Gas Agency",
            invoice_bank_account_number="5010 0123 4567",
            invoice_bank_ifsc="hdfc0001234",
        )
        assert payload.upi_id == "madhavgas@ybl"
        assert payload.invoice_bank_ifsc == "HDFC0001234"
        assert payload.invoice_bank_account_number == "501001234567"

    def test_a_malformed_vpa_is_refused_on_update_too(self):
        with pytest.raises(ValidationError, match="name@bank"):
            MerchantUpdate(upi_id="not-a-vpa")

    def test_a_malformed_ifsc_is_refused_on_update_too(self):
        with pytest.raises(ValidationError, match="HDFC0001234"):
            MerchantUpdate(invoice_bank_ifsc="HDFC1001234")
