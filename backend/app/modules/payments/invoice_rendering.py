"""The invoice-book layout shared by browser print and downloadable PDFs."""
from __future__ import annotations

import base64
import html
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.modules.payments.invoice_documents import _printed_date, _qr_data_uri, _words


@lru_cache(maxsize=1)
def _brand_logo() -> str:
    """Bundle the existing MBGA mark so PDF/print never depend on an external image URL."""
    data = Path(__file__).with_name("assets").joinpath("mbga-logo.png").read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def render_html(document: dict[str, Any]) -> str:
    """Present stored invoice facts in the reference A4 layout without changing the ledger."""
    def e(value: object | None) -> str:
        return html.escape(str(value if value not in (None, "") else "-"))

    def money(value: int | float | Decimal | None) -> str:
        amount = Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"₹{amount:,.2f}"

    merchant, customer = document.get("merchant", {}), document.get("customer", {})
    dispatch, tax = document.get("dispatch", {}), document.get("tax", {})
    compliance, settings = document.get("compliance", {}), document.get("settings", {})
    items = document.get("items") or []
    gst_percent = float(tax.get("gstPercent") or 0)
    total = int(tax.get("totalAmount") or 0)
    taxable = int(tax.get("taxableAmount") or 0)
    is_gst = document.get("documentType") == "TAX_INVOICE"
    # The registration flag controls compliance fields, not whether GST was charged.
    # Unregistered buyers can still receive an invoice that includes a GST breakdown.
    title = "Tax Invoice" if is_gst or Decimal(str(tax.get("gstAmount") or 0)) > 0 else "Cash Memo"

    signed_qr = compliance.get("signedQrCode")
    # Never replace a filed invoice's official QR with a locally constructed payload.
    qr_value = signed_qr or (None if compliance.get("irn") else document.get("verificationQrData"))
    qr_label = "e-Invoice QR" if signed_qr else "Verification QR"
    qr_block = (f"{qr_label}<img src='{_qr_data_uri(str(qr_value))}' alt='{qr_label}'>"
                if qr_value else "e-Invoice QR unavailable")
    references = [
        ("IRN", compliance.get("irn")),
        ("Ack No.", compliance.get("acknowledgementNumber")),
        ("Ack Date.", _printed_date(compliance["acknowledgementDate"])
         if compliance.get("acknowledgementDate") else None),
    ]
    irn_rows = "".join(
        f"<tr><th>{label}</th><td>{e(value)}</td></tr>"
        for label, value in references if value
    )
    eway_reference = (
        f"<div><b>e-Way Bill No.</b><br>{e(compliance.get('ewayBillNumber'))}</div>"
        if is_gst else ""
    )

    # The reference's Amount column is before tax. Allocate the stored taxable total,
    # rather than changing ledger totals or adding tax again to inclusive line amounts.
    gross_total = sum(int(item.get("lineAmount") or 0) for item in items)
    taxable_remaining = Decimal(taxable)
    rows = []
    for n, item in enumerate(items, 1):
        qty = float(item.get("quantity") or 0)
        inclusive = int(item.get("unitPrice") or 0)
        net_amount = (
            taxable_remaining if n == len(items) else
            (Decimal(taxable) * Decimal(int(item.get("lineAmount") or 0)) / Decimal(gross_total))
            .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        ) if gross_total else Decimal(0)
        taxable_remaining -= net_amount
        exclusive = net_amount / Decimal(str(qty)) if qty else Decimal(0)
        unit = e(item.get("unit") or "PCS")
        rows.append(
            f"<tr class='item'><td>{n}</td><td><b>{e(item.get('description'))}</b></td>"
            f"<td>{e(item.get('hsnSac'))}</td><td class='center'>{qty:g} {unit}</td>"
            f"<td class='right'>{money(inclusive)}</td><td class='right'>{money(exclusive)}</td>"
            f"<td class='center'>{unit}</td><td class='right'><b>{money(net_amount)}</b></td></tr>"
        )
    if not rows:
        rows.append("<tr class='item'><td></td><td>No billable items</td>" + "<td></td>" * 6 + "</tr>")

    same_state = tax.get("taxType") == "CGST_SGST"
    components = (
        [("SGST", gst_percent / 2, tax.get("sgstAmount")),
         ("CGST", gst_percent / 2, tax.get("cgstAmount"))]
        if same_state else [("IGST", gst_percent, tax.get("igstAmount"))]
    )
    tax_rows = "".join(
        f"<tr class='tax-line'><td></td><td class='right'><b>{name} ({percent:g}%)</b></td>"
        f"<td></td><td></td><td></td><td class='right'>{percent:g}</td><td>%</td>"
        f"<td class='right'>{money(amount)}</td></tr>"
        for name, percent, amount in components if amount
    )
    if same_state:
        tax_header = "<th colspan='2'>CGST</th><th colspan='2'>SGST</th>"
        tax_subheader = "<th>Rate</th><th>Amount</th><th>Rate</th><th>Amount</th>"
        tax_values = (f"<td>{gst_percent / 2:g}%</td><td>{money(tax.get('cgstAmount'))}</td>"
                      f"<td>{gst_percent / 2:g}%</td><td>{money(tax.get('sgstAmount'))}</td>")
    else:
        tax_header = "<th colspan='2'>IGST</th>"
        tax_subheader = "<th>Rate</th><th>Amount</th>"
        tax_values = f"<td>{gst_percent:g}%</td><td>{money(tax.get('igstAmount'))}</td>"
    hsn_codes = ", ".join(dict.fromkeys(str(item["hsnSac"]) for item in items if item.get("hsnSac")))
    quantity = sum(float(item.get("quantity") or 0) for item in items)
    declaration = settings.get("invoiceDeclaration") or (
        "We declare that this invoice shows the actual price of the goods described "
        "and that all particulars are true and correct."
    )
    return f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><title>{e(document.get('invoiceNumber'))}</title>
<style>
@page {{ size:A4; margin:7mm; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; color:#111; font-family:Arial,Helvetica,sans-serif; font-size:9px; line-height:1.15; }}
.sheet {{ width:196mm; margin:auto; }}
table {{ width:100%; border-collapse:collapse; table-layout:fixed; }}
td,th {{ border:.2mm solid #222; padding:1mm 1.4mm; vertical-align:top; overflow-wrap:anywhere; }}
th {{ font-weight:normal; text-align:left; }}
.top {{ position:relative; min-height:44mm; padding-top:12mm; padding-right:44mm; }}
.heading {{ position:absolute; top:0; left:0; width:100%; text-align:center; }}
h1 {{ margin:0; font-size:16px; line-height:1.2; }}
.copy {{ margin-top:2mm; font-size:8px; font-style:italic; }}
.irn {{ width:113mm; font-size:8px; }}
.irn th,.irn td {{ border:0; padding:.5mm 0; }}
.irn th {{ width:18mm; font-weight:bold; }}
.irn td {{ word-break:break-all; }}
.qr {{ position:absolute; top:0; right:0; width:42mm; text-align:center; font-size:8px; font-weight:bold; }}
.qr img {{ display:block; width:40mm; height:40mm; margin:1mm auto; image-rendering:pixelated; }}
.parties > tbody > tr > td {{ padding:0; }}
.supplier,.address-block {{ padding:1.4mm; }}
.supplier {{ min-height:27mm; display:flex; align-items:flex-start; gap:3mm; }}
.logo {{ width:19mm; height:23mm; object-fit:contain; flex-shrink:0; }}
.agency-details {{ flex:1; min-width:0; }}
.brand {{ font-size:11px; font-weight:bold; text-transform:uppercase; }}
.address-block {{ min-height:22mm; border-top:.2mm solid #222; }}
.address-block b {{ text-transform:uppercase; }}
.meta {{ padding:0!important; }}
.ref td {{ height:7.6mm; border-top:0; border-right:0; }}
.ref td:first-child {{ border-left:0; }}
.ref tr:last-child td {{ border-bottom:0; }}
.invoice-reference {{ display:flex; justify-content:space-between; gap:1.5mm; }}
.invoice-reference > div {{ min-width:0; }}
.goods {{ margin-top:-.2mm; }}
.goods th {{ text-align:center; font-size:8px; padding:1.2mm .6mm; }}
.goods tbody td {{ border-top:0; border-bottom:0; }}
.goods .item td {{ padding-top:2mm; padding-bottom:2mm; }}
.goods .filler td {{ height:38mm; }}
.goods .tax-line td {{ padding-top:.5mm; padding-bottom:.5mm; }}
.goods .total td {{ border-top:.2mm solid #222; border-bottom:.2mm solid #222; padding-top:1.5mm; padding-bottom:1.5mm; }}
.right {{ text-align:right; }} .center {{ text-align:center; }}
.grand {{ font-weight:bold; font-size:11px; }}
.words {{ padding:1.2mm 1.4mm; border:.2mm solid #222; border-top:0; }}
.words b {{ display:block; }}
.amount-caption {{ display:flex; justify-content:space-between; gap:3mm; }}
.errors-omissions {{ white-space:nowrap; font-style:italic; }}
.goods td:nth-child(7) {{ white-space:nowrap; padding-left:.6mm; padding-right:.6mm; }}
.tax-summary {{ margin-top:-.2mm; }}
.tax-summary th,.tax-summary td {{ text-align:center; padding:.8mm 1mm; }}
.footer {{ margin-top:-.2mm; break-inside:avoid; }}
.footer td {{ height:34mm; padding:2mm; }}
.declaration {{ margin-top:7mm; }}
.bank {{ display:grid; grid-template-columns:28mm 1fr; column-gap:1mm; }}
.signature {{ text-align:right; margin-top:3mm; }}
.signature-space {{ height:7mm; }}
.generated {{ margin:1.5mm 0 0; text-align:center; font-size:8px; }}
tr {{ break-inside:avoid; }}
@media print {{ body {{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }} }}
</style></head><body><main class='sheet'>
<header class='top'>
<div class='heading'><h1>{title}</h1><div class='copy'>({e(document.get('copyLabel') or 'ORIGINAL FOR RECIPIENT')})</div></div>
<table class='irn'>{irn_rows}</table><div class='qr'>{qr_block}</div>
</header>
<table class='parties'><colgroup><col style='width:59%'><col style='width:41%'></colgroup><tbody><tr>
<td><div class='supplier'><img class='logo' src='{_brand_logo()}' alt='MBGA logo'><div class='agency-details'>
<div class='brand'>{e(merchant.get('name'))}</div>{e(merchant.get('address'))}<br>
GSTIN/UIN: {e(merchant.get('gstin'))}<br>State Name: {e(merchant.get('state'))}<br>
Contact: {e(merchant.get('mobileNumber'))}<br>E-Mail: {e(merchant.get('email'))}</div></div>
<div class='address-block'>Consignee (Ship to)<br><b>{e(customer.get('deliverySiteName') or customer.get('name'))}</b><br>
{e(customer.get('address'))}<br>GSTIN/UIN: {e(customer.get('gstin'))}<br>State Name: {e(customer.get('state'))}</div>
<div class='address-block'>Buyer (Bill to)<br><b>{e(customer.get('name'))}</b><br>{e(customer.get('address'))}<br>
GSTIN/UIN: {e(customer.get('gstin'))}<br>State Name: {e(customer.get('state'))}<br>Mobile: {e(customer.get('mobileNumber'))}</div></td>
<td class='meta'><table class='ref'><tbody>
<tr><td colspan='2'><div class='invoice-reference'><div><b>Invoice No.</b><br><b>{e(document.get('invoiceNumber'))}</b></div>{eway_reference}<div><b>Dated</b><br>{e(_printed_date(document.get('issuedAt')))}</div></div></td></tr>
<tr><td>Delivery Note<br>{e(dispatch.get('deliverySlipNumber'))}</td><td>Mode/Terms of Payment<br>{e(compliance.get('termsOfDelivery'))}</td></tr>
<tr><td>Reference No. &amp; Date<br>{e(compliance.get('transportDocumentNumber'))}</td><td>Other References<br>-</td></tr>
<tr><td>Buyer's Order No.<br>{e(document.get('order',{}).get('orderNumber'))}</td><td>Dated<br>{e(_printed_date(document.get('order',{}).get('scheduledDeliveryDate')))}</td></tr>
<tr><td>Dispatch Doc No.<br>{e(dispatch.get('deliverySlipNumber'))}</td><td>Delivery Note Date<br>{e(_printed_date(dispatch.get('deliveredAt')))}</td></tr>
<tr><td>Dispatched through<br>{e(dispatch.get('driverName'))}</td><td>Destination<br>{e(dispatch.get('destination'))}</td></tr>
<tr><td>Bill of Lading/LR-RR No.<br>{e(compliance.get('lrNumber'))}</td><td>Motor Vehicle No.<br>{e(dispatch.get('vehicleNumber'))}</td></tr>
<tr><td colspan='2'>Terms of Delivery: {e(compliance.get('termsOfDelivery'))}</td></tr>
</tbody></table></td></tr></tbody></table>
<table class='goods'><colgroup><col style='width:4%'><col style='width:42%'><col style='width:8%'><col style='width:9%'><col style='width:10%'><col style='width:10%'><col style='width:4%'><col style='width:13%'></colgroup>
<thead><tr><th>Sl.<br>No.</th><th>Description of Goods</th><th>HSN/SAC</th><th>Quantity</th><th>Rate<br>(Incl. of Tax)</th><th>Rate</th><th>per</th><th>Amount</th></tr></thead>
<tbody>{''.join(rows)}<tr class='filler'>{'<td></td>' * 8}</tr>{tax_rows}
<tr class='tax-line'><td></td><td class='right'><b>Round Off.</b></td><td></td><td></td><td></td><td></td><td></td><td class='right'>{money(0)}</td></tr>
<tr class='total'><td colspan='3' class='right'><b>Total</b></td><td class='center'><b>{quantity:g} PCS</b></td><td colspan='3'></td><td class='right grand'>{money(total)}</td></tr></tbody></table>
<div class='words'><div class='amount-caption'><span>Amount Chargeable (in words)</span><span class='errors-omissions'>E. &amp; O.E.</span></div><b>{_words(total)}</b></div>
<table class='tax-summary'><thead><tr><th rowspan='2'>HSN/SAC</th><th rowspan='2'>Taxable Value</th>{tax_header}<th rowspan='2'>Total Tax Amount</th></tr><tr>{tax_subheader}</tr></thead>
<tbody><tr><td>{e(hsn_codes)}</td><td>{money(taxable)}</td>{tax_values}<td>{money(tax.get('gstAmount'))}</td></tr></tbody></table>
<div class='words'>Tax Amount (in words): <strong>{_words(int(tax.get('gstAmount') or 0))}</strong></div>
<table class='footer'><colgroup><col style='width:50%'><col style='width:50%'></colgroup><tr><td>
Company's PAN: <b>{e(settings.get('invoicePan'))}</b><div class='declaration'><u>Declaration</u><br>{e(declaration)}</div></td>
<td><b>Company's Bank Details</b><div class='bank'><span>A/c Holder's Name:</span><b>{e(settings.get('invoiceBankAccountName'))}</b>
<span>Bank Name:</span><b>{e(settings.get('invoiceBankName'))}</b><span>A/c No.:</span><b>{e(settings.get('invoiceBankAccountNumber'))}</b>
<span>Branch &amp; IFSC Code:</span><b>{e(settings.get('invoiceBankIfsc'))}</b></div>
<div class='signature'><b>for {e(merchant.get('name'))}</b><div class='signature-space'></div>Authorised Signatory</div></td></tr></table>
<div class='generated'>This is a Computer Generated Invoice</div>
</main></body></html>"""


def render_pdf(document: dict[str, Any]) -> bytes:
    """Render the print HTML; never silently issue a different, incomplete invoice."""
    from app.shared.exceptions.api_error import ApiError

    try:
        from weasyprint import HTML
        return HTML(string=render_html(document)).write_pdf()
    except (ImportError, OSError) as error:
        import logging
        logging.getLogger(__name__).exception("Invoice PDF renderer unavailable")
        raise ApiError(status_code=503, code="INVOICE_PDF_UNAVAILABLE",
                       message="Invoice PDF rendering is temporarily unavailable. Please use Print or try again later.") from error
