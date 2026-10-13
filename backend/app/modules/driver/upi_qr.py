"""Build a standard UPI deep link and render it as an in-memory PNG QR code."""

from base64 import b64encode
from io import BytesIO
from urllib.parse import quote, urlencode

import qrcode
from PIL import Image
from qrcode.constants import ERROR_CORRECT_M

QR_SIZE = 300
QR_DARK = "#14261f"
QR_LIGHT = "#ffffff"

#: NPCI caps a transaction note at 50 characters.
NOTE_LIMIT = 50


def build_upi_link(
    *,
    upi_id: str,
    payee_name: str,
    amount: str,
    order_id: str,
    notes: str | None = None,
) -> str:
    """Build the URI understood by Google Pay, PhonePe, Paytm, BHIM and bank UPI apps.

    The order reference travels in `tn`, the free-text note, and deliberately not in `tr`.
    `tr` is the *merchant* transaction reference: a payer bank that sees it reads the QR as a
    merchant collect and looks for the merchant fields that go with it - `mc`, `mid`, a signed
    `sign`. A gas agency collecting on a personal VPA has none of those, so the request fails
    validation at the payer's bank and is reversed. It reversed at ICICI while the same QR paid
    fine from the payee's own PhonePe, which is the signature of that check: an app paying
    itself never leaves the wallet to be validated. NPCI also caps `tr` at 35 alphanumeric
    characters, and an order id is a 36-character UUID with hyphens - over the limit either way.
    """
    params = [
        ("pa", upi_id),
        ("pn", payee_name),
        ("am", amount),
        ("cu", "INR"),
    ]
    note = notes or f"Order {order_id}"
    params.append(("tn", note[:NOTE_LIMIT]))
    return "upi://pay?" + urlencode(params, quote_via=quote, safe="@")


def png_base64(link: str, *, size: int = QR_SIZE) -> str:
    """Return raw Base64 (without a data-URL prefix) for a square RGB PNG."""
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(link)
    qr.make(fit=True)
    image = qr.make_image(fill_color=QR_DARK, back_color=QR_LIGHT).convert("RGB")
    image = image.resize((size, size), Image.Resampling.NEAREST)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return b64encode(buffer.getvalue()).decode("ascii")
