"""The gateway-free UPI link and PNG returned to the Delivery App."""

from base64 import b64decode
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from app.modules.driver.schemas import GenerateQrRequest
from app.modules.driver.upi_qr import QR_SIZE, build_upi_link, png_base64

pytestmark = [pytest.mark.unit]


def test_dynamic_upi_fields_and_order_reference_are_encoded() -> None:
    link = build_upi_link(
        upi_id="merchant@bank",
        payee_name="MBGA Indore & Sons",
        amount="3200.50",
        order_id="order-1042",
        notes="Order #1042 / Gate 2",
    )

    parsed = urlparse(link)
    values = parse_qs(parsed.query)
    assert (parsed.scheme, parsed.netloc) == ("upi", "pay")
    assert values == {
        "pa": ["merchant@bank"],
        "pn": ["MBGA Indore & Sons"],
        "am": ["3200.50"],
        "cu": ["INR"],
        "tn": ["Order #1042 / Gate 2"],
    }
    # `tr` marks the link as a merchant collect, and a payer bank then rejects it for the
    # merchant fields a personal VPA cannot supply. See `build_upi_link`.
    assert "tr" not in values


def test_without_a_note_the_order_is_still_referenced() -> None:
    """The driver and the customer both need to see which order the money was for."""
    link = build_upi_link(
        upi_id="merchant@bank",
        payee_name="MBGA",
        amount="100.00",
        order_id="order-7",
    )

    assert parse_qs(urlparse(link).query)["tn"] == ["Order order-7"]


def test_a_long_note_is_cut_to_what_upi_accepts() -> None:
    """NPCI caps `tn` at 50 characters; a longer one is refused by the payer app."""
    link = build_upi_link(
        upi_id="merchant@bank",
        payee_name="MBGA",
        amount="100.00",
        order_id="order-7",
        notes="x" * 200,
    )

    assert len(parse_qs(urlparse(link).query)["tn"][0]) == 50


def test_base64_is_a_real_300_pixel_png() -> None:
    encoded = png_base64(
        build_upi_link(
            upi_id="merchant@bank",
            payee_name="MBGA",
            amount="100.00",
            order_id="order-1",
        )
    )

    image = b64decode(encoded, validate=True)
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert int.from_bytes(image[16:20], "big") == QR_SIZE
    assert int.from_bytes(image[20:24], "big") == QR_SIZE


def test_request_trims_order_reference_and_rejects_non_positive_amount() -> None:
    request = GenerateQrRequest(
        orderId=" order-1 ",
        amount=1.005,
        notes=" Order #1 ",
    )
    assert (request.order_id, request.notes) == (
        "order-1",
        "Order #1",
    )

    with pytest.raises(ValidationError):
        GenerateQrRequest(
            orderId="order-1",
            amount=0,
        )
