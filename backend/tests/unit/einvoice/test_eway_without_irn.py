"""The consignment that has no IRN but still needs an e-Way Bill.

This is the case the slice originally dropped: an invoice over fifty thousand rupees sold to
a customer with no GST registration filed nothing at all, because the queueing rule tested
the buyer's GSTIN before it tested anything else. Goods then moved without the document the
law requires them to carry.

The tests here pin the rule that replaced it - the two requirements are independent - and
the payload that the separate e-Way Bill API is sent.
"""

import pytest

from app.modules.einvoice.constants import (
    EWAY_BILL_THRESHOLD,
    UNREGISTERED_PARTY,
    needs_eway_bill,
    needs_irn,
)
from app.modules.einvoice.eway_payload import build_eway_payload
from app.modules.einvoice.payload import PayloadError


def snapshot(**overrides):
    base = {
        "issuedAt": "2026-10-30T11:32:00Z",
        "merchant": {
            "name": "Madhav Bharat Gas Agency",
            "gstin": "23AARFB4347G000",
            "address": "5th block, Bengaluru City, Madhya Pradesh, 462001",
            "state": "Madhya Pradesh",
            "mobileNumber": "9000000000",
            "email": "office@example.com",
        },
        "customer": {
            # No GSTIN: this is the whole point of the route.
            "name": "Ramesh Kumar",
            "gstin": None,
            "address": "7th block, Kuvempu layout, Madhya Pradesh, 462003",
            "state": "Madhya Pradesh",
            "mobileNumber": "9000000001",
        },
        "tax": {
            "taxableAmount": 60000,
            "gstPercent": 5,
            "gstAmount": 3000,
            "cgstAmount": 1500,
            "sgstAmount": 1500,
            "igstAmount": 0,
            "totalAmount": 63000,
            "taxType": "CGST_SGST",
        },
        "items": [
            {
                "description": "19kg commercial",
                "hsnSac": "271119",
                "quantity": 30,
                "unitPrice": 2100,
                "lineAmount": 63000,
            }
        ],
        "dispatch": {"vehicleNumber": "MP 09 AB 1234"},
    }
    base.update(overrides)
    return base


class TestTheTwoRulesAreIndependent:
    def test_an_unregistered_buyer_over_the_threshold_still_needs_a_bill(self):
        # The regression this slice was missing. The buyer has no GSTIN, so no IRN applies -
        # but the goods are worth more than fifty thousand and must carry a bill.
        assert needs_irn(None) is False
        assert needs_eway_bill(63_000) is True

    def test_a_registered_buyer_under_the_threshold_needs_only_an_irn(self):
        assert needs_irn("23AWGPV7107B1Z1") is True
        assert needs_eway_bill(10_000) is False

    def test_an_ordinary_domestic_sale_needs_neither(self):
        assert needs_irn("") is False
        assert needs_eway_bill(EWAY_BILL_THRESHOLD) is False

    def test_needs_irn_ignores_whitespace(self):
        # A column holding "  " is not a registration, and treating it as one would send a
        # B2B document the portal rejects.
        assert needs_irn("   ") is False


class TestPayload:
    def test_an_unregistered_buyer_is_sent_as_urp(self):
        payload = build_eway_payload(snapshot(), invoice_number="MBGA/26-27/0061")
        assert payload["toGstin"] == UNREGISTERED_PARTY
        assert payload["toTrdName"] == "Ramesh Kumar"

    def test_the_buyer_state_comes_from_the_address_when_there_is_no_gstin(self):
        # With no GSTIN there are no first two digits to read, so the delivery address is
        # the only source for the state that decides the tax treatment.
        payload = build_eway_payload(snapshot(), invoice_number="MBGA/26-27/0061")
        assert payload["toStateCode"] == 23
        assert payload["actToStateCode"] == 23

    def test_an_unrecognised_state_is_refused_rather_than_guessed(self):
        data = snapshot()
        data["customer"] = {**data["customer"], "state": "Westeros"}
        with pytest.raises(PayloadError, match="not a state we recognise"):
            build_eway_payload(data, invoice_number="MBGA/26-27/0061")

    def test_amounts_are_sent_tax_exclusive(self):
        payload = build_eway_payload(snapshot(), invoice_number="MBGA/26-27/0061")
        assert payload["totalValue"] == 60000
        assert payload["totInvValue"] == 63000

    def test_cgst_and_sgst_are_exactly_equal(self):
        # The same portal rule as the e-invoice call, and the same odd-rupee trap.
        data = snapshot()
        data["tax"] = {**data["tax"], "gstAmount": 3715}
        payload = build_eway_payload(data, invoice_number="MBGA/26-27/0061")
        assert payload["cgstValue"] == payload["sgstValue"]
        assert payload["cgstValue"] + payload["sgstValue"] == 3715

    def test_interstate_supply_is_sent_as_igst(self):
        data = snapshot()
        data["tax"] = {**data["tax"], "taxType": "IGST"}
        data["customer"] = {**data["customer"], "state": "Maharashtra"}
        payload = build_eway_payload(data, invoice_number="MBGA/26-27/0061")
        assert payload["igstValue"] == 3000
        assert payload["cgstValue"] == 0 and payload["sgstValue"] == 0
        assert payload["toStateCode"] == 27
        assert payload["itemList"][0]["igstRate"] == 5
        assert payload["itemList"][0]["cgstRate"] == 0

    def test_lines_add_back_up_to_the_taxable_value(self):
        payload = build_eway_payload(snapshot(), invoice_number="MBGA/26-27/0061")
        assert sum(line["taxableAmount"] for line in payload["itemList"]) == payload["totalValue"]

    def test_the_vehicle_plate_is_stripped_of_spaces_and_dashes(self):
        payload = build_eway_payload(snapshot(), invoice_number="MBGA/26-27/0061")
        assert payload["vehicleNo"] == "MP09AB1234"

    def test_no_vehicle_names_the_problem(self):
        data = snapshot(dispatch={})
        with pytest.raises(PayloadError, match="vehicle number"):
            build_eway_payload(data, invoice_number="MBGA/26-27/0061")

    def test_the_seller_must_still_be_registered(self):
        # The bill is raised under the agency's own registration; without it there is no
        # account to raise it on.
        data = snapshot()
        data["merchant"] = {**data["merchant"], "gstin": None}
        with pytest.raises(PayloadError, match="merchant has no GSTIN"):
            build_eway_payload(data, invoice_number="MBGA/26-27/0061")

    def test_the_agency_is_its_own_transporter(self):
        payload = build_eway_payload(snapshot(), invoice_number="MBGA/26-27/0061")
        assert payload["transporterId"] == "23AARFB4347G000"
        assert payload["transDistance"] == "0"

    def test_date_is_sent_in_the_portals_format_and_timezone(self):
        data = snapshot(issuedAt="2026-10-30T18:40:00Z")
        payload = build_eway_payload(data, invoice_number="MBGA/26-27/0061")
        assert payload["docDate"] == "31/10/2026"

    def test_a_registered_buyer_keeps_their_own_gstin(self):
        # The route is normally only taken for an unregistered buyer, but the builder does
        # not assume that: a registered party's own GSTIN and state are used when present.
        data = snapshot()
        data["customer"] = {**data["customer"], "gstin": "27AWGPV7107B1Z1"}
        payload = build_eway_payload(data, invoice_number="MBGA/26-27/0061")
        assert payload["toGstin"] == "27AWGPV7107B1Z1"
        assert payload["toStateCode"] == 27
