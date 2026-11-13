"""The invoice document, written the way the GST portal wants to read it.

**Built from the snapshot, not from live tables.** `invoices.document_snapshot` is frozen at
issue time precisely because an invoice is a statement about a moment. The IRN the portal
returns certifies *that* document, so the payload has to be built from the same frozen copy -
otherwise a customer renamed, or a price card revised, between the handover and the worker's
pass would have us certify a document nobody ever issued.

**Whole rupees in, rupees out.** This platform stores GST-inclusive whole rupees and splits
tax out of the total (`app.shared.money`). The portal wants it the other way round: a taxable
value with tax stated beside it. Both numbers are already on the invoice row, so the split is
copied rather than recomputed - recomputing it here is how the document and the government
record start disagreeing by a rupee.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.einvoice.constants import (
    DOCUMENT_TYPE_INVOICE,
    SUPPLY_TYPE_B2B,
    TRANSPORT_MODE_ROAD,
    VEHICLE_TYPE_REGULAR,
    state_code_from_gstin,
)

#: The portal reads dates as they are written on the paper document, in India.
_IST = ZoneInfo("Asia/Kolkata")

#: NIC's schema version for the GENERATE call.
PAYLOAD_VERSION = "1.1"


class PayloadError(ValueError):
    """The invoice cannot be expressed as an e-invoice.

    Raised for data the portal would reject anyway - a missing seller GSTIN, an unknown
    state, a consignment with no vehicle. Failing here, with the field named, is worth more
    than a rejection later: the message says what to fix rather than what NIC called it.
    """


def _nic_date(value: str | None) -> str:
    """`dd/mm/yyyy`, which is the only date format the portal accepts."""
    if not value:
        raise PayloadError("The invoice has no issue date.")
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment.astimezone(_IST).strftime("%d/%m/%Y")


def _pin(value: object | None) -> int:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) != 6:
        raise PayloadError(f"'{value}' is not a six-digit pincode.")
    return int(digits)


def _trimmed(value: object | None, limit: int) -> str | None:
    """The portal rejects over-long fields outright, so they are cut rather than sent."""
    text = str(value or "").strip()
    return text[:limit] or None


def _phone(value: object | None) -> str | None:
    """A phone number the portal will accept: six to twelve digits, nothing else.

    Numbers are stored here with a country code (`+919000000000`), and the portal matches
    `^([0-9]{6,12})$` - a `+` fails it outright, and a thirteen-digit number fails the
    length. So the digits are taken alone and a leading `91` is dropped when that is what
    makes it too long. Too few digits returns None rather than a number that would be
    rejected: the field is optional, and sending nothing is better than sending nonsense.
    """
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) > 10 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) < 6:
        return None
    return digits[:12]


def _half(amount: int) -> float | int:
    """Half of a tax amount, as a number the portal will accept on both sides of the split.

    CGST and SGST must be identical, so an odd number of rupees becomes two halves ending in
    .5 rather than a rupee handed to one side. Whole results stay integers, which is what the
    portal's examples show and what keeps the common case free of a pointless `.0`.
    """
    if amount % 2 == 0:
        return amount // 2
    return round(amount / 2, 2)


def _party(block: dict[str, Any], *, role: str) -> tuple[str, str]:
    """A party's GSTIN and state code, or a message naming what is missing."""
    gstin = _trimmed(block.get("gstin"), 15)
    if not gstin:
        raise PayloadError(f"The {role} has no GSTIN on this invoice.")
    code = state_code_from_gstin(gstin)
    if not code:
        raise PayloadError(f"The {role} GSTIN '{gstin}' does not start with a state code.")
    return gstin, code


def _address_parts(address: str | None) -> tuple[str, str | None]:
    """One stored address line split into the two the portal asks for."""
    text = (address or "").strip()
    if not text:
        raise PayloadError("The address is empty.")
    pieces = [part.strip() for part in text.split(",") if part.strip()]
    first = pieces[0] if pieces else text
    rest = ", ".join(pieces[1:]) if len(pieces) > 1 else None
    return first[:100], (rest[:100] if rest else None)


def _last_pin(address: str | None) -> str | None:
    """The six digits at the end of a stored address line."""
    for part in reversed([piece.strip() for piece in (address or "").split(",")]):
        digits = "".join(ch for ch in part if ch.isdigit())
        if len(digits) == 6:
            return digits
    return None


def build_generate_payload(
    snapshot: dict[str, Any],
    *,
    invoice_number: str,
    with_eway_bill: bool,
) -> dict[str, Any]:
    """The GENERATE request body for one issued invoice.

    `with_eway_bill` is decided by the caller from the invoice total and frozen on the job,
    so a later correction cannot change what was asked for after the fact.
    """
    merchant = snapshot.get("merchant") or {}
    customer = snapshot.get("customer") or {}
    tax = snapshot.get("tax") or {}
    items = snapshot.get("items") or []
    dispatch = snapshot.get("dispatch") or {}

    if not items:
        raise PayloadError("The invoice has no billable lines.")

    seller_gstin, seller_state = _party(merchant, role="merchant")
    buyer_gstin, buyer_state = _party(customer, role="customer")

    seller_line1, seller_line2 = _address_parts(merchant.get("address"))
    buyer_line1, buyer_line2 = _address_parts(customer.get("address"))

    # The portal validates tax treatment against the GSTIN state prefix. A registered buyer's
    # delivery address can be in another state; letting that address win made the government
    # record disagree with the frozen invoice.
    place_of_supply = buyer_state

    # Which tax applies was settled when the document was frozen; it is not re-derived here,
    # or the printed invoice and the government record could disagree about the split.
    is_igst = tax.get("taxType") == "IGST"
    taxable_total = int(tax.get("taxableAmount") or 0)
    invoice_total = max(int(tax.get("totalAmount") or 0), 1)

    item_list: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        quantity = int(item.get("quantity") or 0)
        line_amount = int(item.get("lineAmount") or 0)
        if quantity <= 0 or line_amount <= 0:
            continue
        # The stored line is GST-inclusive; the portal wants it exclusive. Each line is
        # scaled by the ratio the invoice total was already split by, so the lines add back
        # up to the taxable value the document states rather than drifting from it.
        taxable = round(line_amount * taxable_total / invoice_total)
        line_tax = line_amount - taxable
        item_list.append(
            {
                "SlNo": str(index),
                "IsServc": "N",
                "PrdDesc": _trimmed(item.get("description"), 300) or "LPG cylinder",
                "HsnCd": _trimmed(item.get("hsnSac"), 8) or "271119",
                "Qty": quantity,
                "FreeQty": 0,
                "Unit": "NOS",
                "UnitPrice": round(taxable / quantity, 3),
                "TotAmt": taxable,
                "Discount": 0,
                "PreTaxVal": 0,
                "AssAmt": taxable,
                "GstRt": float(tax.get("gstPercent") or 0),
                "IgstAmt": line_tax if is_igst else 0,
                # Split to the paisa, not to the rupee. The portal requires CGST and SGST to
                # be *exactly* equal, and an odd rupee of tax split as 1857/1858 is rejected
                # with "SGST and CGST amounts are not equal" - so a half-rupee is carried
                # rather than rounded away.
                "CgstAmt": 0 if is_igst else _half(line_tax),
                "SgstAmt": 0 if is_igst else _half(line_tax),
                "CesRt": 0,
                "CesAmt": 0,
                "CesNonAdvlAmt": 0,
                "StateCesRt": 0,
                "StateCesAmt": 0,
                "StateCesNonAdvlAmt": 0,
                "OthChrg": 0,
                "TotItemVal": line_amount,
            }
        )

    if not item_list:
        raise PayloadError("Every line on this invoice is zero-valued.")

    payload: dict[str, Any] = {
        "Version": PAYLOAD_VERSION,
        "TranDtls": {
            "TaxSch": "GST",
            "SupTyp": SUPPLY_TYPE_B2B,
            "RegRev": "N",
            "EcmGstin": None,
            "IgstOnIntra": "N",
        },
        "DocDtls": {
            "Typ": DOCUMENT_TYPE_INVOICE,
            # The portal's identifier for this document is our own invoice number, so the two
            # records can always be matched back to each other.
            "No": invoice_number,
            "Dt": _nic_date(snapshot.get("issuedAt")),
        },
        "SellerDtls": {
            "Gstin": seller_gstin,
            "LglNm": _trimmed(merchant.get("name"), 100),
            "TrdNm": _trimmed(merchant.get("name"), 100),
            "Addr1": seller_line1,
            "Addr2": seller_line2,
            "Loc": _trimmed(merchant.get("state"), 50) or "NA",
            "Pin": _pin(_last_pin(merchant.get("address"))),
            "Stcd": seller_state,
            "Ph": _phone(merchant.get("mobileNumber")),
            "Em": _trimmed(merchant.get("email"), 50),
        },
        "BuyerDtls": {
            "Gstin": buyer_gstin,
            "LglNm": _trimmed(customer.get("name"), 100),
            "TrdNm": _trimmed(customer.get("name"), 100),
            "Pos": place_of_supply,
            "Addr1": buyer_line1,
            "Addr2": buyer_line2,
            "Loc": _trimmed(customer.get("state"), 50) or "NA",
            "Pin": _pin(_last_pin(customer.get("address"))),
            "Stcd": buyer_state,
            "Ph": _phone(customer.get("mobileNumber")),
            "Em": _trimmed(customer.get("email"), 50),
        },
        "ItemList": item_list,
        "ValDtls": {
            "AssVal": taxable_total,
            # Equal halves here too, for the same reason - and taken from the invoice's own
            # GST total so the two halves add back up to it rather than to a rounded pair.
            "CgstVal": 0 if is_igst else _half(int(tax.get("gstAmount") or 0)),
            "SgstVal": 0 if is_igst else _half(int(tax.get("gstAmount") or 0)),
            "IgstVal": int(tax.get("igstAmount") or 0) if is_igst else 0,
            "CesVal": 0,
            "StCesVal": 0,
            "Discount": 0,
            "OthChrg": 0,
            "RndOffAmt": 0,
            "TotInvVal": int(tax.get("totalAmount") or 0),
        },
    }

    if with_eway_bill:
        # Only the vehicle is sent. `Distance: 0` asks the portal to work the distance out
        # from the two pincodes, which is more trustworthy than a number nobody measured.
        vehicle = _trimmed(dispatch.get("vehicleNumber"), 20)
        if not vehicle:
            raise PayloadError(
                "This consignment needs an e-Way Bill but the delivery slip records no vehicle number."
            )
        payload["EwbDtls"] = {
            "TransMode": TRANSPORT_MODE_ROAD,
            "Distance": 0,
            "Vehno": vehicle.replace(" ", "").replace("-", "").upper(),
            "Vehtype": VEHICLE_TYPE_REGULAR,
        }

    return payload
