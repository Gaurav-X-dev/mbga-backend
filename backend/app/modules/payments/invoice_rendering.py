"""Printable GST invoice presentation shared by every application channel."""

from __future__ import annotations

import html
from typing import Any

from app.modules.payments.invoice_documents import (
    _money,
    _printed_date,
    _qr_data_uri,
    _safe_pdf_text,
    _words,
)


def render_html(document: dict[str, Any]) -> str:
    """Render the compact A4 tax-invoice layout based on the supplied MBGA invoice book."""
    def e(value: object | None) -> str:
        return html.escape(str(value if value not in (None, "") else "-"))

    merchant, customer = document.get("merchant", {}), document.get("customer", {})
    dispatch, tax = document.get("dispatch", {}), document.get("tax", {})
    compliance, settings = document.get("compliance", {}), document.get("settings", {})
    gst_percent, total = float(tax.get("gstPercent") or 0), int(tax.get("totalAmount") or 0)
    taxable = int(tax.get("taxableAmount") or 0)
    qr = _qr_data_uri(str(document.get("verificationQrData") or document.get("invoiceNumber") or "MBGA"))
    rows = ""
    for n, item in enumerate(document.get("items") or [], 1):
        qty, amount, inclusive = float(item.get("quantity") or 0), int(item.get("lineAmount") or 0), int(item.get("unitPrice") or 0)
        exclusive = round(inclusive / (1 + gst_percent / 100), 2) if gst_percent else inclusive
        rows += f"<tr class='item'><td>{n}</td><td><b>{e(item.get('description'))}</b></td><td>{e(item.get('hsnSac'))}</td><td>{qty:g} {e(item.get('unit') or 'PCS')}</td><td class='right'>{_money(inclusive)}</td><td class='right'>{_money(exclusive)}</td><td>PCS</td><td class='right'><b>{_money(amount)}</b></td></tr>"
    if not rows:
        rows = "<tr class='item'><td colspan='8'>No billable items</td></tr>"
    if tax.get("taxType") == "CGST_SGST":
        tax_note = f"<p><b>SGST @{gst_percent/2:g}%</b><span>{_money(tax.get('sgstAmount'))}</span></p><p><b>CGST @{gst_percent/2:g}%</b><span>{_money(tax.get('cgstAmount'))}</span></p>"
        tax_header = "<th>CGST Rate</th><th>CGST Amount</th><th>SGST Rate</th><th>SGST Amount</th><th>Total Tax</th>"
        tax_values = f"<td>{gst_percent/2:g}%</td><td>{_money(tax.get('cgstAmount'))}</td><td>{gst_percent/2:g}%</td><td>{_money(tax.get('sgstAmount'))}</td><td>{_money(tax.get('gstAmount'))}</td>"
    else:
        tax_note = f"<p><b>IGST @{gst_percent:g}%</b><span>{_money(tax.get('igstAmount'))}</span></p>"
        tax_header = "<th>IGST Rate</th><th>IGST Amount</th><th>CGST/SGST Rate</th><th>CGST/SGST Amount</th><th>Total Tax</th>"
        tax_values = f"<td>{gst_percent:g}%</td><td>{_money(tax.get('igstAmount'))}</td><td>-</td><td>-</td><td>{_money(tax.get('gstAmount'))}</td>"
    irn_rows = "".join(f"<p><b>{e(label)}</b><span>{e(value)}</span></p>" for label, value in [("IRN", compliance.get("irn")), ("Ack No.", compliance.get("acknowledgementNumber")), ("Ack Date.", _printed_date(compliance.get("acknowledgementDate")))] if value) or "<p><b>IRN</b><span>Not generated</span></p>"
    title = "Tax Invoice" if document.get("documentType") == "TAX_INVOICE" else "Cash Memo"
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>{e(document.get('invoiceNumber'))}</title><style>
@page{{size:A4;margin:7mm}}*{{box-sizing:border-box}}body{{font-family:Arial,Helvetica,sans-serif;font-size:9px;line-height:1.12;color:#111;margin:0}}.sheet{{width:196mm;margin:auto}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #222;padding:1.4mm;vertical-align:top}}.top{{display:grid;grid-template-columns:1fr 1.2fr 34mm;min-height:37mm}}.irn{{padding-top:8mm;font-size:8px;word-break:break-all}}.irn p,.tax-note p{{display:flex;gap:4mm;margin:1mm 0}}.irn b{{min-width:16mm}}.heading{{text-align:center;padding-top:7mm;font-size:16px;font-weight:bold}}.copy{{text-align:center;font-style:italic;font-size:9px;margin-top:2mm}}.qr{{text-align:center;font-weight:bold;font-size:8px}}.qr img{{display:block;width:29mm;height:29mm;margin:2mm auto}}.brand{{font-weight:bold;font-size:13px}}.party td{{height:28mm}}.ref td{{height:6mm}}.goods th{{text-align:center;font-size:8px}}.goods .item td{{height:8mm}}.filler td{{height:36mm}}.right{{text-align:right}}.center{{text-align:center}}.tax-note{{text-align:right;padding:2mm 3mm}}.tax-note p{{justify-content:flex-end;gap:12mm}}.grand{{font-size:12px;font-weight:bold}}.words{{font-weight:bold}}.tax-summary th,.tax-summary td{{text-align:center}}.footer td{{height:29mm}}.signature{{text-align:right!important;vertical-align:bottom!important}}.generated{{text-align:center;color:#444;font-size:8px;margin:2mm}}@media print{{body{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}}}</style></head><body><main class='sheet'>
<section class='top'><div class='irn'>{irn_rows}</div><div><div class='heading'>{e(title)}</div><div class='copy'>({e(document.get('copyLabel') or 'ORIGINAL FOR RECIPIENT')})</div></div><div class='qr'>Verification QR<img src='{qr}' alt='Invoice verification QR'></div></section>
<table class='party'><tr><td style='width:56%'><div class='brand'>{e(merchant.get('name'))}</div>{e(merchant.get('address'))}<br>GSTIN/UIN: {e(merchant.get('gstin'))}<br>State Name: {e(merchant.get('state'))}<br>Contact: {e(merchant.get('mobileNumber'))}<br>E-Mail: {e(merchant.get('email'))}</td><td style='width:44%'><table class='ref'><tr><td><b>Invoice No.</b><br><b>{e(document.get('invoiceNumber'))}</b><br>Delivery Note<br>{e(dispatch.get('deliverySlipNumber'))}</td><td><b>Dated</b><br>{e(_printed_date(document.get('issuedAt')))}<br>Mode/Terms of Payment<br>{e(compliance.get('termsOfDelivery'))}</td></tr><tr><td>Reference No. & Date<br>{e(compliance.get('transportDocumentNumber'))}</td><td>Other References<br>{e(compliance.get('ewayBillNumber'))}</td></tr><tr><td>Buyer's Order No.<br>{e(document.get('order',{}).get('orderNumber'))}</td><td>Dated<br>{e(_printed_date(document.get('order',{}).get('scheduledDeliveryDate')))}</td></tr><tr><td>Dispatch Doc No.<br>{e(dispatch.get('deliverySlipNumber'))}</td><td>Delivery Note Date<br>{e(_printed_date(dispatch.get('deliveredAt')))}</td></tr><tr><td>Dispatched through<br>{e(dispatch.get('driverName'))}</td><td>Destination<br>{e(dispatch.get('destination'))}</td></tr><tr><td>Bill of Lading/LR-RR No.<br>{e(compliance.get('lrNumber'))}</td><td>Motor Vehicle No.<br>{e(dispatch.get('vehicleNumber'))}</td></tr><tr><td colspan='2'>Terms of Delivery: {e(compliance.get('termsOfDelivery'))}</td></tr></table></td></tr></table>
<table class='party'><tr><td>Consignee (Ship to)<br><b>{e(customer.get('deliverySiteName') or customer.get('name'))}</b><br>{e(customer.get('address'))}<br>GSTIN/UIN: {e(customer.get('gstin'))}<br>State Name: {e(customer.get('state'))}</td></tr><tr><td>Buyer (Bill to)<br><b>{e(customer.get('name'))}</b><br>{e(customer.get('address'))}<br>GSTIN/UIN: {e(customer.get('gstin'))}<br>Mobile: {e(customer.get('mobileNumber'))}</td></tr></table>
<table class='goods'><thead><tr><th>Sl<br>No.</th><th>Description of Goods</th><th>HSN/SAC</th><th>Quantity</th><th>Rate<br>(Incl. of Tax)</th><th>Rate</th><th>per</th><th>Amount</th></tr></thead><tbody>{rows}<tr class='filler'><td></td><td colspan='6'><div class='tax-note'>{tax_note}<p><b>Round Off.</b><span>{_money(0)}</span></p></div></td><td></td></tr><tr><td colspan='3' class='right'><b>Total</b></td><td class='center'><b>{sum(float(x.get('quantity') or 0) for x in document.get('items') or []):g} PCS</b></td><td colspan='3'></td><td class='right grand'>{_money(total)}</td></tr></tbody></table>
<table><tr><td class='words'>Amount Chargeable (in words)<br>INR {_words(total)} Only</td></tr></table><table class='tax-summary'><tr><th>HSN/SAC</th><th>Taxable Value</th>{tax_header}</tr><tr><td>{e((document.get('items') or [{}])[0].get('hsnSac'))}</td><td>{_money(taxable)}</td>{tax_values}</tr></table><table><tr><td class='words'>Tax Amount (in words): INR {_words(int(tax.get('gstAmount') or 0))} Only</td></tr></table>
<table class='footer'><tr><td><b>Company's PAN</b>: {e(settings.get('invoicePan'))}<br><br><b>Declaration</b><br>We declare that this invoice shows the actual price of the goods described and that all particulars are true and correct.</td><td class='signature'><b>Company's Bank Details</b><br>A/c Holder's Name: {e(settings.get('invoiceBankAccountName'))}<br>Bank Name: {e(settings.get('invoiceBankName'))}<br>A/c No.: {e(settings.get('invoiceBankAccountNumber'))}<br>Branch & IFSC Code: {e(settings.get('invoiceBankIfsc'))}<br><br><b>for {e(merchant.get('name'))}</b><br><br>Authorised Signatory</td></tr></table><div class='generated'>This is a Computer Generated Invoice | Verification: {e(document.get('verificationQrData'))}</div></main></body></html>"""


def render_pdf(document: dict[str, Any]) -> bytes:
    """Render the same detailed HTML layout to PDF, with a safe built-in fallback."""
    try:
        from weasyprint import HTML
    except (ImportError, OSError):
        # The fallback keeps downloads available during a rolling deployment before the
        # optional rendering package/native libraries have finished installing.
        pass
    else:
        return HTML(string=render_html(document)).write_pdf()

    merchant, customer, tax = document.get("merchant", {}), document.get("customer", {}), document.get("tax", {})
    lines = ["TAX INVOICE", f"Invoice No.: {document.get('invoiceNumber') or '-'}", f"Date: {_printed_date(document.get('issuedAt'))}", "", f"Supplier: {merchant.get('name') or '-'}", str(merchant.get('address') or '-'), f"GSTIN: {merchant.get('gstin') or '-'}", "", f"Bill To: {customer.get('name') or '-'}", str(customer.get('address') or '-'), "", "Description                                      Qty       Amount"]
    for item in document.get("items") or []: lines.append(f"{str(item.get('description') or '-')[:42]:42} {item.get('quantity') or 0!s:>5} PCS  {_money(item.get('lineAmount'))}")
    lines.extend(["", f"Taxable value: {_money(tax.get('taxableAmount'))}", f"GST: {_money(tax.get('gstAmount'))}", f"GRAND TOTAL: {_money(tax.get('totalAmount'))}", f"Amount in words: INR {_words(int(tax.get('totalAmount') or 0))} Only", "", "This is a Computer Generated Invoice."])
    commands = ["BT", "/F2 15 Tf", "42 800 Td", f"({_safe_pdf_text(lines[0])}) Tj", "0 -22 Td", "/F1 9 Tf"]
    for line in lines[1:]: commands += [f"({_safe_pdf_text(line)}) Tj", "0 -13 Td"]
    commands.append("ET"); stream = "\n".join(commands).encode("latin-1")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>", b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>", b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)]
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"); offsets = [0]
    for num, obj in enumerate(objects, 1): offsets.append(len(output)); output.extend(f"{num} 0 obj\n".encode()); output.extend(obj); output.extend(b"\nendobj\n")
    xref = len(output); output.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]: output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()); return bytes(output)
