"""Rules and codes the e-invoice slice is built on.

Two government rules decide what happens to an invoice, and they are independent of each
other:

* **IRN** - an Invoice Reference Number is obtained for a supply to a registered buyer. In
  this platform that is simply "the customer has a GSTIN": a domestic LPG customer is a B2C
  sale and the portal would reject it.
* **e-Way Bill** - required once the consignment is worth more than fifty thousand rupees.
  It travels with the goods, so it is about the value being moved, **not about who is
  buying**. An unregistered customer's consignment needs one exactly as a registered one
  does; the buyer is named `URP` in place of a GSTIN.

The two are independent, which gives three outcomes rather than two:

===========================  ==============  =====================================
Buyer has a GSTIN?           Over 50,000?    What is filed
===========================  ==============  =====================================
yes                          no              IRN alone
yes                          yes             IRN with the e-Way Bill inside it
no                           yes             e-Way Bill alone, buyer as `URP`
no                           no              nothing - an ordinary domestic sale
===========================  ==============  =====================================

The third row is the one that is easy to miss, and missing it is a compliance failure, not
a cosmetic gap: goods move without the document the law requires them to carry. It needs the
provider's *separate* e-Way Bill API, because there is no IRN for the bill to live inside.

The threshold is read off the invoice total the platform actually billed - never recomputed
from the lines, which would let the document and the government record disagree.
"""

from enum import Enum

#: Rupees. Above this an e-Way Bill accompanies the consignment. Whole rupees, like every
#: other amount in this platform - see `app.shared.money`.
EWAY_BILL_THRESHOLD = 50_000


class EInvoiceStatus(str, Enum):
    """Where one invoice has got to with the portal."""

    #: Queued; the worker has not picked it up yet.
    PENDING = "PENDING"
    #: Sent and accepted. `irn` is on the invoice row.
    DONE = "DONE"
    #: The portal rejected it, or the transport failed. `last_error` says which.
    FAILED = "FAILED"
    #: Tried enough times, and the error was not one that retrying fixes. Needs a human.
    ABANDONED = "ABANDONED"
    #: Deliberately not sent: a B2C sale, or the feature is off for this merchant.
    SKIPPED = "SKIPPED"


#: How many times a retryable failure is tried before it is abandoned. A rejection from the
#: portal is usually about the data, and retrying bad data forever just hides it.
MAX_ATTEMPTS = 5

#: Back-off between attempts, in minutes, by attempt number.
RETRY_BACKOFF_MINUTES = (2, 10, 30, 120, 360)

#: NIC document types. The platform only raises sales invoices today; credit and debit notes
#: would be `CRN` and `DBN` when the refund slice needs them.
DOCUMENT_TYPE_INVOICE = "INV"

#: Supply type on the e-invoice call. Only `B2B` is reachable there: an IRN is asked for
#: only when the buyer has a GSTIN.
SUPPLY_TYPE_B2B = "B2B"

#: What the e-Way Bill portal calls a buyer who is not registered for GST. It goes in the
#: GSTIN field, which is why that field is never left empty: the portal reads a blank as a
#: missing value and rejects it, but `URP` as a deliberate statement that there is no
#: registration to quote.
UNREGISTERED_PARTY = "URP"

#: e-Way Bill: an outward supply, which is the only direction a gas agency raises one in.
#: (`I` would be a purchase return coming back in.)
EWAY_SUPPLY_TYPE_OUTWARD = "O"
#: Sub-supply type `1` is a supply against a sale - as opposed to a transfer, an export or
#: job work, none of which this platform raises.
EWAY_SUB_SUPPLY_SALE = "1"
#: Transaction type `1` is a plain bill-to/ship-to-the-same-party sale. The provider's own
#: sample uses `4` (bill-to and ship-to differ), which is not this platform's case: the
#: customer being billed is the customer the cylinders are delivered to.
EWAY_TRANSACTION_REGULAR = 1
#: Kilograms. The only unit LPG is sold in here, and the portal wants a code, not a word.
EWAY_QTY_UNIT = "KGS"

#: Road. The only transport mode a gas agency's own fleet uses.
TRANSPORT_MODE_ROAD = "1"
#: Regular vehicle, as opposed to over-dimensional cargo.
VEHICLE_TYPE_REGULAR = "R"

#: GST state codes, keyed by the state name this platform stores. The portal wants the
#: numeric code, and the two parties' codes decide CGST+SGST versus IGST.
#:
#: Only used for the *shipping* address: both parties' own codes are taken from the first two
#: digits of their GSTIN, which is authoritative and cannot drift from a spelling.
STATE_CODES: dict[str, str] = {
    "jammu and kashmir": "01",
    "himachal pradesh": "02",
    "punjab": "03",
    "chandigarh": "04",
    "uttarakhand": "05",
    "haryana": "06",
    "delhi": "07",
    "rajasthan": "08",
    "uttar pradesh": "09",
    "bihar": "10",
    "sikkim": "11",
    "arunachal pradesh": "12",
    "nagaland": "13",
    "manipur": "14",
    "mizoram": "15",
    "tripura": "16",
    "meghalaya": "17",
    "assam": "18",
    "west bengal": "19",
    "jharkhand": "20",
    "odisha": "21",
    "orissa": "21",
    "chhattisgarh": "22",
    "madhya pradesh": "23",
    "gujarat": "24",
    "dadra and nagar haveli and daman and diu": "26",
    "maharashtra": "27",
    "andhra pradesh": "37",
    "karnataka": "29",
    "goa": "30",
    "lakshadweep": "31",
    "kerala": "32",
    "tamil nadu": "33",
    "puducherry": "34",
    "andaman and nicobar islands": "35",
    "telangana": "36",
    "ladakh": "38",
    "other territory": "97",
}


def state_code(name: str | None) -> str | None:
    """The GST code for a state name, or None when it is not one we know.

    Returning None rather than guessing matters: a wrong state code on an e-Way Bill is a
    wrong tax treatment, and the portal will either reject it or - worse - accept it.
    """
    if not name:
        return None
    return STATE_CODES.get(name.strip().lower())


def state_code_from_gstin(gstin: str | None) -> str | None:
    """The state code a GSTIN carries in its first two digits."""
    cleaned = (gstin or "").strip()
    if len(cleaned) < 2 or not cleaned[:2].isdigit():
        return None
    return cleaned[:2]


def needs_eway_bill(total_amount: int) -> bool:
    """True when this consignment value must travel with an e-Way Bill.

    Deliberately says nothing about the buyer. The e-Way Bill follows the goods, so an
    unregistered customer's consignment needs one on exactly the same terms - and tying this
    to the GSTIN is the bug this function exists to keep out of the rest of the slice.
    """
    return int(total_amount) > EWAY_BILL_THRESHOLD


def needs_irn(gstin: str | None) -> bool:
    """True when an IRN applies: the buyer is registered for GST.

    A sale to an unregistered customer is B2C. The portal rejects a B2C document outright, so
    sending one would only manufacture errors for staff to read.
    """
    return bool((gstin or "").strip())
