"""One immutable invoice document contract for Customer, Merchant and Admin.

The JSON document is the source used by every client.  The HTML endpoint renders exactly the
same payload for print/share/WebView, so each app never has to reimplement a tax invoice.
"""

from __future__ import annotations

import base64
import html
import io
import json
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import qrcode
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.models import CustomerProfile
from app.modules.deliveries.models import DeliverySlip
from app.modules.merchants.models import Merchant
from app.modules.orders.constants import ORDER_LABELS
from app.modules.orders.models import Order, OrderItem
from app.modules.payments.models import Invoice


def _clean(value: object | None) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _address(*parts: object | None) -> str:
    return ", ".join(part for part in (_clean(value) for value in parts) if part)


def _money(value: int | None) -> str:
    return f"₹{int(value or 0):,}"


def _date(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _printed_date(value: str | None) -> str:
    """The printed document is read in India, not in UTC."""
    if not value:
        return "—"
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return str(value)
    return moment.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%d-%b-%y")


def _words(value: int) -> str:
    """Small dependency-free Indian-number formatter for the statutory total line."""
    ones = ("", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen")
    tens = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")
    def below_thousand(number: int) -> str:
        parts: list[str] = []
        if number >= 100:
            parts.append(f"{ones[number // 100]} Hundred")
            number %= 100
        if number >= 20:
            parts.append(tens[number // 10])
            number %= 10
        if number:
            parts.append(ones[number])
        return " ".join(parts)
    amount = max(int(value or 0), 0)
    groups = ((10_000_000, "Crore"), (100_000, "Lakh"), (1_000, "Thousand"))
    parts: list[str] = []
    for divisor, label in groups:
        if amount >= divisor:
            parts.append(f"{below_thousand(amount // divisor)} {label}")
            amount %= divisor
    if amount or not parts:
        parts.append(below_thousand(amount) or "Zero")
    return "INR " + " ".join(parts) + " Only"


def _qr_data_uri(value: str) -> str:
    """An internal verification QR. It is never labelled as a government e-invoice QR."""
    image = qrcode.make(value)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def _state_key(value: str | None) -> str:
    return " ".join((value or "").upper().split())


def merchant_settings_view(merchant: Merchant) -> dict[str, Any]:
    """Only printable business configuration; never expose admin/internal merchant fields."""
    return {
        "invoicePan": merchant.invoice_pan,
        "invoiceBankName": merchant.invoice_bank_name,
        "invoiceBankAccountName": merchant.invoice_bank_account_name,
        "invoiceBankAccountNumber": merchant.invoice_bank_account_number,
        "invoiceBankIfsc": merchant.invoice_bank_ifsc,
        "invoiceLogoUrl": merchant.invoice_logo_url,
        "invoiceSignatureUrl": merchant.invoice_signature_url,
        "invoiceTerms": merchant.invoice_terms,
        "invoiceDeclaration": merchant.invoice_declaration,
        "invoiceHsnSac": merchant.invoice_hsn_sac or "271119",
    }


async def build_issue_snapshot(
    session: AsyncSession,
    *,
    invoice: Invoice,
    order: Order,
    customer: CustomerProfile | None,
    delivered: dict[str, int] | None,
) -> dict[str, Any]:
    """Build the legal document payload once, immediately before the invoice is inserted."""
    merchant = await session.get(Merchant, invoice.merchant_id)
    slip = await session.scalar(
        select(DeliverySlip).where(DeliverySlip.order_id == order.id).order_by(DeliverySlip.created_at.desc())
    )
    lines = list(await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.position)))
    invoice_lines: list[dict[str, Any]] = []
    for line in lines:
        quantity = line.quantity if delivered is None else min(delivered.get(line.cylinder_type, 0), line.quantity)
        if quantity <= 0:
            continue
        label = next(
            (value for key, value in ORDER_LABELS.items() if key.value == line.cylinder_type),
            line.cylinder_type.replace("_", " "),
        )
        invoice_lines.append(
            {
                "cylinderType": line.cylinder_type,
                "description": label,
                "hsnSac": (merchant.invoice_hsn_sac if merchant else None) or "271119",
                "quantity": quantity,
                "unit": "PCS",
                "unitPrice": int(line.unit_price),
                "lineAmount": int(line.unit_price) * quantity,
            }
        )
    same_state = bool(
        merchant and _state_key(merchant.state) and _state_key(merchant.state) == _state_key(order.address_state)
    )
    gst = int(invoice.gst_amount)
    tax = {
        "taxableAmount": int(invoice.amount),
        "gstPercent": int(invoice.gst_percent),
        "gstAmount": gst,
        "cgstAmount": gst // 2 if same_state else 0,
        "sgstAmount": gst - (gst // 2) if same_state else 0,
        "igstAmount": gst if not same_state else 0,
        "totalAmount": int(invoice.total_amount),
        "taxType": "CGST_SGST" if same_state else "IGST",
    }
    settings = merchant_settings_view(merchant) if merchant else merchant_settings_view_placeholder()
    return {
        "version": 1,
        "issuedAt": _date(invoice.issued_at),
        "documentType": "TAX_INVOICE" if invoice.is_gst_invoice else "CASH_MEMO",
        "copyLabel": "ORIGINAL FOR RECIPIENT",
        "merchant": {
            "id": invoice.merchant_id,
            "name": merchant.name if merchant else None,
            "code": merchant.code if merchant else None,
            "mobileNumber": merchant.mobile_number if merchant else None,
            "email": merchant.email if merchant else None,
            "gstin": merchant.gst_number if merchant else None,
            "address": _address(
                merchant.address_line_1 if merchant else None,
                merchant.address_line_2 if merchant else None,
                merchant.city if merchant else None,
                merchant.state if merchant else None,
                merchant.postal_code if merchant else None,
            ),
            "state": merchant.state if merchant else None,
        },
        "customer": {
            "id": invoice.customer_id,
            "name": invoice.customer_name,
            "mobileNumber": customer.mobile_number if customer else None,
            "email": customer.email if customer else None,
            "gstin": invoice.gstin,
            "customerType": order.customer_type,
            "address": _address(order.address_line1, order.address_line2, order.address_city, order.address_state, order.address_pincode),
            "state": order.address_state,
            "deliverySiteName": order.delivery_site_name,
        },
        "order": {"id": order.id, "orderNumber": order.order_number, "scheduledDeliveryDate": str(order.scheduled_delivery_date)},
        "dispatch": {
            "deliverySlipId": slip.id if slip else order.delivery_slip_id,
            "deliverySlipNumber": slip.slip_number if slip else None,
            "vehicleNumber": slip.vehicle_number if slip else None,
            "driverName": slip.driver_name if slip else None,
            "deliveredAt": _date(slip.delivered_at) if slip else None,
            "destination": _address(order.address_city, order.address_state, order.address_pincode),
        },
        "items": invoice_lines,
        "tax": tax,
        "settings": settings,
    }


def merchant_settings_view_placeholder() -> dict[str, Any]:
    return {"invoiceHsnSac": "271119"}


def read_snapshot(invoice: Invoice) -> dict[str, Any] | None:
    if not invoice.document_snapshot:
        return None
    try:
        loaded = json.loads(invoice.document_snapshot)
    except (TypeError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def document_payload(invoice: Invoice, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Add live payment/compliance state to the immutable issue-time snapshot."""
    return {
        "invoiceId": invoice.id,
        "invoiceNumber": invoice.invoice_number,
        "documentType": snapshot.get("documentType", "TAX_INVOICE" if invoice.is_gst_invoice else "CASH_MEMO"),
        "snapshotVersion": snapshot.get("version", 1),
        "isLegacySnapshot": not bool(invoice.document_snapshot),
        "copyLabel": snapshot.get("copyLabel", "ORIGINAL FOR RECIPIENT"),
        "issuedAt": _date(invoice.issued_at),
        "dueAt": _date(invoice.due_at),
        "merchant": snapshot.get("merchant", {}),
        "customer": snapshot.get("customer", {}),
        "order": snapshot.get("order", {}),
        "dispatch": snapshot.get("dispatch", {}),
        "items": snapshot.get("items", []),
        "tax": snapshot.get("tax", {}),
        "settings": snapshot.get("settings", {}),
        "payment": {"paidAmount": int(invoice.paid_amount), "balance": int(invoice.balance), "status": invoice.status},
        "compliance": {
            "irn": invoice.irn,
            "acknowledgementNumber": invoice.acknowledgement_number,
            "acknowledgementDate": _date(invoice.acknowledgement_date),
            "ewayBillNumber": invoice.eway_bill_number,
            "ewayBillDate": _date(invoice.eway_bill_date),
            "transportDocumentNumber": invoice.transport_document_number,
            "lrNumber": invoice.lr_number,
            "termsOfDelivery": invoice.terms_of_delivery or snapshot.get("settings", {}).get("invoiceTerms"),
        },
        # This is an internal verification payload, not a government e-invoice QR / IRN claim.
        "verificationQrData": f"MBGA|{invoice.merchant_id}|{invoice.invoice_number}|{invoice.id}",
    }


def _safe_pdf_text(value: object | None) -> str:
    return str(value or "-").encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def render_html(document: dict[str, Any]) -> str:
    """Print-safe GST tax-invoice layout, modelled on the paper invoice supplied by MBGA."""
    def e(value: object | None) -> str:
        return html.escape(str(value if value not in (None, "") else "—"))

    merchant = document["merchant"]
    customer = document["customer"]
    tax = document["tax"]
    compliance = document["compliance"]
    settings = document["settings"]
    rows = "".join(
        f"<tr><td>{index}</td><td>{e(item.get('description'))}</td><td>{e(item.get('hsnSac'))}</td>"
        f"<td class='right'>{e(item.get('quantity'))} {e(item.get('unit'))}</td>"
        f"<td class='right'>{_money(item.get('unitPrice'))}</td><td class='right'>{_money(item.get('lineAmount'))}</td></tr>"
        for index, item in enumerate(document["items"], start=1)
    ) or "<tr><td colspan='6'>No billable items</td></tr>"
    tax_rows = (
        f"<tr><td>CGST ({tax.get('gstPercent', 0) / 2:g}%)</td><td class='right'>{_money(tax.get('cgstAmount'))}</td></tr>"
        f"<tr><td>SGST ({tax.get('gstPercent', 0) / 2:g}%)</td><td class='right'>{_money(tax.get('sgstAmount'))}</td></tr>"
        if tax.get("taxType") == "CGST_SGST"
        else f"<tr><td>IGST ({tax.get('gstPercent', 0)}%)</td><td class='right'>{_money(tax.get('igstAmount'))}</td></tr>"
    )
    official = "<br>".join(
        f"<b>{e(label)}:</b> {e(value)}" for label, value in (
            ("IRN", compliance.get("irn")), ("Acknowledgement", compliance.get("acknowledgementNumber")),
            ("e-Way Bill", compliance.get("ewayBillNumber")), ("LR / RR", compliance.get("lrNumber")),
        ) if value
    ) or "Not applicable / not entered"
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>{e(document['invoiceNumber'])}</title>
    <style>@page{{size:A4;margin:11mm}}*{{box-sizing:border-box}}body{{font-family:Arial,sans-serif;color:#172033;font-size:11px;margin:0}}.head{{display:flex;justify-content:space-between;border-bottom:2px solid #172033;padding-bottom:9px}}h1{{font-size:20px;margin:0}}h2{{font-size:13px;margin:0 0 4px}}p{{margin:2px 0}}.muted{{color:#586174}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}}.box{{border:1px solid #9ba7b6;padding:7px;min-height:76px}}table{{width:100%;border-collapse:collapse;margin-top:10px}}th,td{{border:1px solid #9ba7b6;padding:5px;text-align:left;vertical-align:top}}th{{background:#edf2f7}}.right{{text-align:right}}.totals{{margin-left:auto;width:280px}}.total td{{font-weight:bold;font-size:13px}}.footer{{margin-top:16px;border-top:1px solid #9ba7b6;padding-top:8px;display:grid;grid-template-columns:1fr 1fr;gap:12px}}@media print{{.no-print{{display:none}}}}</style></head><body>
    <div class='head'><div><h1>{e(document['documentType'].replace('_', ' '))}</h1><p>{e(document['copyLabel'])}</p></div><div class='right'><h2>Invoice {e(document['invoiceNumber'])}</h2><p>Date: {e(document['issuedAt'][:10] if document['issuedAt'] else None)}</p><p>Order: {e(document['order'].get('orderNumber'))}</p></div></div>
    <div class='grid'><section class='box'><h2>Supplier</h2><b>{e(merchant.get('name'))}</b><p>{e(merchant.get('address'))}</p><p>GSTIN: {e(merchant.get('gstin'))}</p><p>PAN: {e(settings.get('invoicePan'))}</p></section><section class='box'><h2>Bill To / Consignee</h2><b>{e(customer.get('name'))}</b><p>{e(customer.get('address'))}</p><p>GSTIN: {e(customer.get('gstin'))}</p><p>Mobile: {e(customer.get('mobileNumber'))}</p></section></div>
    <div class='grid'><section class='box'><h2>Dispatch</h2><p>Vehicle: {e(document['dispatch'].get('vehicleNumber'))}</p><p>Driver: {e(document['dispatch'].get('driverName'))}</p><p>Destination: {e(document['dispatch'].get('destination'))}</p></section><section class='box'><h2>e-Invoice / Transport references</h2><p>{official}</p></section></div>
    <table><thead><tr><th>#</th><th>Description of Goods</th><th>HSN/SAC</th><th class='right'>Quantity</th><th class='right'>Rate (incl. tax)</th><th class='right'>Amount</th></tr></thead><tbody>{rows}</tbody></table>
    <table class='totals'><tr><td>Taxable value</td><td class='right'>{_money(tax.get('taxableAmount'))}</td></tr>{tax_rows}<tr class='total'><td>Grand total</td><td class='right'>{_money(tax.get('totalAmount'))}</td></tr><tr><td>Paid / Balance</td><td class='right'>{_money(document['payment']['paidAmount'])} / {_money(document['payment']['balance'])}</td></tr></table>
    <div class='footer'><section><b>Declaration</b><p>{e(settings.get('invoiceDeclaration') or 'We declare that this invoice shows the actual price of the goods described and that all particulars are true and correct.')}</p><p>{e(compliance.get('termsOfDelivery'))}</p></section><section class='right'><b>Bank details</b><p>{e(settings.get('invoiceBankName'))}</p><p>{e(settings.get('invoiceBankAccountName'))} · {e(settings.get('invoiceBankAccountNumber'))}</p><p>IFSC: {e(settings.get('invoiceBankIfsc'))}</p><br><p>For {e(merchant.get('name'))}</p><p>Authorised Signatory</p></section></div>
    <p class='muted right'>Computer generated invoice · Verification: {e(document['verificationQrData'])}</p></body></html>"""
