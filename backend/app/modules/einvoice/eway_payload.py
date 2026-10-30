"""The e-Way Bill request, for a consignment that has no IRN to carry one.

**Why this exists at all.** An e-Way Bill accompanies goods worth more than fifty thousand
rupees. That rule is about the consignment, not about the customer - so a sale to somebody
with no GST registration needs one exactly as a registered sale does. There is no IRN for an
unregistered sale, so there is nowhere to put an `EwbDtls` block, and the bill has to be
raised on the provider's separate e-Way Bill API instead.

**A different API, not a different payload for the same one.** It has its own path, its own
credentials and its own vocabulary: flat `camelCase` keys, numeric state codes and pincodes
rather than strings, and `taxableAmount` per line instead of NIC's `AssAmt`. Translating
between the two shapes in one builder would make both harder to read against the provider's
documentation, so this is deliberately its own file with its own tests.

Built from `invoices.document_snapshot` for the same reason `payload.py` is: the bill
describes the consignment that was actually handed over, and a price card revised afterwards
must not change what the government was told moved.
"""

from __future__ import annotations

from typing import Any

from app.modules.einvoice.constants import (
    DOCUMENT_TYPE_INVOICE,
    EWAY_QTY_UNIT,
    EWAY_SUB_SUPPLY_SALE,
    EWAY_SUPPLY_TYPE_OUTWARD,
    EWAY_TRANSACTION_REGULAR,
    TRANSPORT_MODE_ROAD,
    UNREGISTERED_PARTY,
    VEHICLE_TYPE_REGULAR,
    state_code,
    state_code_from_gstin,
)
from app.modules.einvoice.payload import (
    PayloadError,
    _address_parts,
    _half,
    _last_pin,
    _nic_date,
    _pin,
    _trimmed,
)


def build_eway_payload(
    snapshot: dict[str, Any],
    *,
    invoice_number: str,
) -> dict[str, Any]:
    """The `genewaybill` request body for one issued invoice.

    Called only for a consignment the IRN route cannot carry - no buyer GSTIN, but over the
    threshold. A registered buyer's bill is raised inside the e-invoice call instead, which
    keeps the two records joined to one IRN rather than sitting apart.
    """
    merchant = snapshot.get("merchant") or {}
    customer = snapshot.get("customer") or {}
    tax = snapshot.get("tax") or {}
    items = snapshot.get("items") or []
    dispatch = snapshot.get("dispatch") or {}

    if not items:
        raise PayloadError("The invoice has no billable lines.")

    # The seller must be registered: the e-Way Bill is raised under its GSTIN, and the
    # portal authenticates the call against that registration.
    seller_gstin = _trimmed(merchant.get("gstin"), 15)
    if not seller_gstin:
        raise PayloadError("The merchant has no GSTIN on this invoice.")
    seller_state = state_code_from_gstin(seller_gstin)
    if not seller_state:
        raise PayloadError(f"The merchant GSTIN '{seller_gstin}' does not start with a state code.")

    # The buyer is the one party that may be unregistered - that is the whole point of this
    # route. `URP` is the portal's word for it, and it goes in the GSTIN field rather than
    # the field being left empty.
    buyer_gstin = _trimmed(customer.get("gstin"), 15) or UNREGISTERED_PARTY
    buyer_state = (
        state_code_from_gstin(buyer_gstin)
        if buyer_gstin != UNREGISTERED_PARTY
        else state_code(customer.get("state"))
    )
    if not buyer_state:
        # Without a GSTIN to read the state from, the delivery address is the only source -
        # and the state decides the tax treatment, so a guess here is worse than a refusal.
        raise PayloadError(
            "This consignment needs an e-Way Bill, but the customer is not registered for GST "
            f"and '{customer.get('state') or 'their address'}' is not a state we recognise."
        )

    vehicle = _trimmed(dispatch.get("vehicleNumber"), 20)
    if not vehicle:
        raise PayloadError(
            "This consignment needs an e-Way Bill but the delivery slip records no vehicle number."
        )

    seller_line1, seller_line2 = _address_parts(merchant.get("address"))
    buyer_line1, buyer_line2 = _address_parts(customer.get("address"))

    is_igst = tax.get("taxType") == "IGST"
    gst_total = int(tax.get("gstAmount") or 0)
    taxable_total = int(tax.get("taxableAmount") or 0)
    invoice_total = max(int(tax.get("totalAmount") or 0), 1)
    gst_rate = float(tax.get("gstPercent") or 0)

    item_list: list[dict[str, Any]] = []
    for item in items:
        quantity = int(item.get("quantity") or 0)
        line_amount = int(item.get("lineAmount") or 0)
        if quantity <= 0 or line_amount <= 0:
            continue
        # Same scaling as the e-invoice payload: the stored line is GST-inclusive and the
        # portal wants it exclusive, so each line is split by the ratio the invoice as a
        # whole was split by and the lines still add up to the taxable total.
        taxable = round(line_amount * taxable_total / invoice_total)
        item_list.append(
            {
                "productName": _trimmed(item.get("description"), 100) or "LPG cylinder",
                "productDesc": _trimmed(item.get("description"), 100) or "LPG cylinder",
                "hsnCode": int(_trimmed(item.get("hsnSac"), 8) or "271119"),
                "quantity": quantity,
                "qtyUnit": EWAY_QTY_UNIT,
                "cgstRate": 0 if is_igst else gst_rate / 2,
                "sgstRate": 0 if is_igst else gst_rate / 2,
                "igstRate": gst_rate if is_igst else 0,
                "cessRate": 0,
                "cessNonadvol": 0,
                "taxableAmount": taxable,
            }
        )

    if not item_list:
        raise PayloadError("Every line on this invoice is zero-valued.")

    return {
        "supplyType": EWAY_SUPPLY_TYPE_OUTWARD,
        "subSupplyType": EWAY_SUB_SUPPLY_SALE,
        "subSupplyDesc": "",
        "docType": DOCUMENT_TYPE_INVOICE,
        "docNo": invoice_number,
        "docDate": _nic_date(snapshot.get("issuedAt")),
        "fromGstin": seller_gstin,
        "fromTrdName": _trimmed(merchant.get("name"), 100),
        "fromAddr1": seller_line1,
        "fromAddr2": seller_line2 or "",
        "fromPlace": _trimmed(merchant.get("state"), 50) or "NA",
        "fromPincode": _pin(_last_pin(merchant.get("address"))),
        # Where the goods actually start and the state the seller is registered in are the
        # same for a gas agency: one godown, one registration.
        "actFromStateCode": int(seller_state),
        "fromStateCode": int(seller_state),
        "toGstin": buyer_gstin,
        "toTrdName": _trimmed(customer.get("name"), 100),
        "toAddr1": buyer_line1,
        "toAddr2": buyer_line2 or "",
        "toPlace": _trimmed(customer.get("state"), 50) or "NA",
        "toPincode": _pin(_last_pin(customer.get("address"))),
        "actToStateCode": int(buyer_state),
        "toStateCode": int(buyer_state),
        "transactionType": EWAY_TRANSACTION_REGULAR,
        "otherValue": "0",
        "totalValue": taxable_total,
        # Equal halves, as on the e-invoice call and for the same reason: the portal refuses
        # a split where the two sides differ, and an odd rupee of tax is the ordinary case.
        "cgstValue": 0 if is_igst else _half(gst_total),
        "sgstValue": 0 if is_igst else _half(gst_total),
        "igstValue": gst_total if is_igst else 0,
        "cessValue": 0,
        "cessNonAdvolValue": 0,
        "totInvValue": int(tax.get("totalAmount") or 0),
        # The agency carries its own cylinders, so it is its own transporter. Distance 0 asks
        # the portal to work the distance out from the two pincodes, which is more
        # trustworthy than a number nobody measured.
        "transporterId": seller_gstin,
        "transporterName": "",
        "transDocNo": "",
        "transMode": TRANSPORT_MODE_ROAD,
        "transDistance": "0",
        "transDocDate": "",
        "vehicleNo": vehicle.replace(" ", "").replace("-", "").upper(),
        "vehicleType": VEHICLE_TYPE_REGULAR,
        "itemList": item_list,
    }
