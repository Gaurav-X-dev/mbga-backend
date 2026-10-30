"""The two government rules, and the payload they produce.

These are pure functions over a frozen snapshot, so they are tested without a database or a
provider - which is the point of building the payload from the snapshot rather than from
live tables.
"""

import pytest

from app.modules.einvoice.constants import (
    EWAY_BILL_THRESHOLD,
    needs_eway_bill,
    state_code,
    state_code_from_gstin,
)
from app.modules.einvoice.payload import PayloadError, build_generate_payload


def snapshot(**overrides):
    base = {
        "issuedAt": "2026-10-23T11:32:00Z",
        "merchant": {
            "name": "Madhav Bharat Gas Agency",
            "gstin": "23AARFB4347G000",
            "address": "5th block, Bengaluru City, Madhya Pradesh, 462001",
            "state": "Madhya Pradesh",
            "mobileNumber": "9000000000",
            "email": "office@example.com",
        },
        "customer": {
            "name": "XYZ Industries",
            "gstin": "23AWGPV7107B1Z1",
            "address": "7th block, Kuvempu layout, Madhya Pradesh, 462003",
            "state": "Madhya Pradesh",
            "mobileNumber": "9000000001",
            "email": "buyer@example.com",
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


class TestRules:
    def test_eway_bill_only_above_fifty_thousand(self):
        assert needs_eway_bill(EWAY_BILL_THRESHOLD + 1) is True
        # Exactly fifty thousand is *not* above the threshold. The rule is "more than", and
        # an off-by-one here files a bill the law does not ask for.
        assert needs_eway_bill(EWAY_BILL_THRESHOLD) is False
        assert needs_eway_bill(4_999) is False

    def test_state_code_comes_from_the_gstin_not_a_spelling(self):
        assert state_code_from_gstin("23AARFB4347G000") == "23"
        assert state_code_from_gstin("") is None
        assert state_code_from_gstin("XXAARFB4347G000") is None

    def test_unknown_state_name_is_not_guessed(self):
        assert state_code("Madhya Pradesh") == "23"
        assert state_code("madhya pradesh") == "23"
        # Returning None matters: a wrong state code is a wrong tax treatment, and the
        # portal may accept it rather than reject it.
        assert state_code("Westeros") is None


class TestPayload:
    def test_amounts_are_sent_tax_exclusive(self):
        payload = build_generate_payload(
            snapshot(), invoice_number="MBGA/INV/0144", with_eway_bill=False
        )
        values = payload["ValDtls"]
        assert values["AssVal"] == 60000
        assert values["TotInvVal"] == 63000
        assert values["CgstVal"] == 1500 and values["SgstVal"] == 1500
        assert values["IgstVal"] == 0

    def test_lines_add_back_up_to_the_taxable_value(self):
        payload = build_generate_payload(
            snapshot(), invoice_number="MBGA/INV/0144", with_eway_bill=False
        )
        lines = payload["ItemList"]
        assert sum(line["AssAmt"] for line in lines) == payload["ValDtls"]["AssVal"]
        assert sum(line["TotItemVal"] for line in lines) == payload["ValDtls"]["TotInvVal"]

    def test_cgst_and_sgst_are_exactly_equal(self):
        # The portal rejects an uneven split outright ("SGST and CGST amounts are not
        # equal"), and an odd number of rupees of tax is the ordinary case - so the halves
        # carry a paisa rather than a rupee going to one side.
        data = snapshot()
        data["tax"] = {**data["tax"], "gstAmount": 3715, "cgstAmount": 1857, "sgstAmount": 1858}
        payload = build_generate_payload(
            data, invoice_number="MBGA/INV/0144", with_eway_bill=False
        )
        values = payload["ValDtls"]
        assert values["CgstVal"] == values["SgstVal"]
        assert values["CgstVal"] + values["SgstVal"] == 3715

        line = payload["ItemList"][0]
        assert line["CgstAmt"] == line["SgstAmt"]

    def test_an_even_tax_split_stays_whole(self):
        payload = build_generate_payload(
            snapshot(), invoice_number="MBGA/INV/0144", with_eway_bill=False
        )
        values = payload["ValDtls"]
        assert values["CgstVal"] == 1500 and values["SgstVal"] == 1500

    def test_interstate_supply_is_sent_as_igst(self):
        data = snapshot()
        data["tax"] = {
            **data["tax"],
            "cgstAmount": 0,
            "sgstAmount": 0,
            "igstAmount": 3000,
            "taxType": "IGST",
        }
        payload = build_generate_payload(
            data, invoice_number="MBGA/INV/0144", with_eway_bill=False
        )
        assert payload["ValDtls"]["IgstVal"] == 3000
        assert payload["ValDtls"]["CgstVal"] == 0
        assert payload["ItemList"][0]["IgstAmt"] == 3000
        assert payload["ItemList"][0]["CgstAmt"] == 0

    def test_eway_bill_block_is_only_added_when_asked_for(self):
        without = build_generate_payload(
            snapshot(), invoice_number="MBGA/INV/0144", with_eway_bill=False
        )
        assert "EwbDtls" not in without

        with_bill = build_generate_payload(
            snapshot(), invoice_number="MBGA/INV/0144", with_eway_bill=True
        )
        # Spaces and dashes are stripped: the portal matches the plate exactly.
        assert with_bill["EwbDtls"]["Vehno"] == "MP09AB1234"
        assert with_bill["EwbDtls"]["Distance"] == 0

    def test_eway_bill_without_a_vehicle_names_the_problem(self):
        data = snapshot(dispatch={})
        with pytest.raises(PayloadError, match="vehicle number"):
            build_generate_payload(data, invoice_number="MBGA/INV/0144", with_eway_bill=True)

    def test_missing_buyer_gstin_names_the_party(self):
        data = snapshot()
        data["customer"] = {**data["customer"], "gstin": None}
        with pytest.raises(PayloadError, match="customer"):
            build_generate_payload(data, invoice_number="MBGA/INV/0144", with_eway_bill=False)

    def test_date_is_sent_in_the_portals_format_and_timezone(self):
        # 2026-10-23T18:40:00Z is already 24 October in India. The document's date is the
        # one printed on it, so it has to be read in IST, not UTC.
        data = snapshot(issuedAt="2026-10-23T18:40:00Z")
        payload = build_generate_payload(
            data, invoice_number="MBGA/INV/0144", with_eway_bill=False
        )
        assert payload["DocDtls"]["Dt"] == "24/10/2026"

    def test_invoice_number_is_the_documents_own_number(self):
        payload = build_generate_payload(
            snapshot(), invoice_number="MBGA/INV/0144", with_eway_bill=False
        )
        assert payload["DocDtls"]["No"] == "MBGA/INV/0144"
