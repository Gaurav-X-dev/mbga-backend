import type { Merchant } from "../../api/merchants.api";
import type { Order } from "../../api/orders.api";
import type { Invoice, Payment } from "../../api/payments.api";

/*
 * A printable invoice, built in the browser because the backend has no PDF endpoint.
 * "Save as PDF" in the print dialog gives the customer a file. Every value is escaped: names
 * and addresses are typed by customers and must never be read as markup.
 */

const escapeHtml = (value: unknown) =>
  String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

const money = (value: number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);

const date = (value: string | null | undefined) =>
  value ? new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric" }).format(new Date(value)) : "—";

const ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"];
const TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"];

function belowHundred(n: number) {
  return n < 20 ? ONES[n] : `${TENS[Math.floor(n / 10)]}${n % 10 ? ` ${ONES[n % 10]}` : ""}`;
}

function belowThousand(n: number) {
  const hundreds = Math.floor(n / 100);
  const rest = n % 100;
  return [hundreds ? `${ONES[hundreds]} Hundred` : "", rest ? belowHundred(rest) : ""].filter(Boolean).join(" ");
}

/** Indian numbering: crore, lakh, thousand. */
export function rupeesInWords(amount: number) {
  let n = Math.round(Math.abs(amount));
  if (n === 0) return "Zero Rupees Only";
  const parts: string[] = [];
  const crore = Math.floor(n / 10_000_000);
  n %= 10_000_000;
  const lakh = Math.floor(n / 100_000);
  n %= 100_000;
  const thousand = Math.floor(n / 1000);
  n %= 1000;
  if (crore) parts.push(`${belowThousand(crore)} Crore`);
  if (lakh) parts.push(`${belowHundred(lakh)} Lakh`);
  if (thousand) parts.push(`${belowHundred(thousand)} Thousand`);
  if (n) parts.push(belowThousand(n));
  return `${parts.join(" ")} Rupees Only`;
}

export function printInvoice({
  invoice,
  order,
  merchant,
  payments
}: {
  invoice: Invoice;
  order?: Order | null;
  merchant?: Merchant | null;
  payments?: Payment[];
}) {
  const win = window.open("", "_blank", "width=900,height=1000");
  if (!win) return false;

  const address = order?.deliveryAddress;
  const billTo = [address?.line1, address?.line2, [address?.city, address?.state].filter(Boolean).join(", "), address?.pincode].filter(Boolean);
  const merchantAddress = [merchant?.address_line_1, merchant?.address_line_2, [merchant?.city, merchant?.state].filter(Boolean).join(", "), merchant?.postal_code].filter(Boolean);
  const items = order?.items ?? [];
  const validPayments = (payments ?? []).map((p) => ({ ...p, amountCollected: p.effectiveAmount ?? (p.reconciliationStatus === "INVALID" ? 0 : p.amountCollected) })).filter((p) => p.amountCollected > 0);

  const rows = items.length
    ? items
        .map(
          (item, index) => `<tr>
            <td>${index + 1}</td>
            <td>${escapeHtml(item.cylinderLabel)}</td>
            <td class="num">${item.quantity}</td>
            <td class="num">${money(item.unitPrice)}</td>
            <td class="num">${money(item.lineTotal)}</td>
          </tr>`
        )
        .join("")
    : `<tr><td colspan="5" class="muted">Order ${escapeHtml(invoice.orderNumber)} (line items unavailable)</td></tr>`;

  const paymentRows = validPayments.length
    ? `<h3>Payments received</h3>
       <table>
         <thead><tr><th>Receipt</th><th>Date</th><th>Mode</th><th>Reference</th><th class="num">Amount</th></tr></thead>
         <tbody>${validPayments
           .map(
             (p) => `<tr><td>${escapeHtml(p.paymentNumber)}</td><td>${date(p.paidAt)}</td><td>${escapeHtml(p.mode)}</td><td>${escapeHtml(p.reference || "—")}</td><td class="num">${money(p.amountCollected)}</td></tr>`
           )
           .join("")}</tbody>
       </table>`
    : "";

  // Same state: CGST + SGST. Different states: one IGST line. Unknown states default to same-state.
  const norm = (v: string | null | undefined) => (v ?? "").trim().toLowerCase();
  const interState = Boolean(norm(merchant?.state) && norm(address?.state) && norm(merchant?.state) !== norm(address?.state));

  const title = invoice.isGstInvoice ? "Tax Invoice" : "Invoice";
  win.document.write(`<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>${escapeHtml(title)} ${escapeHtml(invoice.invoiceNumber)}</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif; color: #111827; margin: 0; padding: 32px; font-size: 13px; }
  .sheet { max-width: 800px; margin: 0 auto; }
  header { display: flex; justify-content: space-between; gap: 24px; border-bottom: 2px solid #111827; padding-bottom: 16px; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  h2 { font-size: 18px; margin: 0; text-transform: uppercase; letter-spacing: 0.08em; text-align: right; }
  h3 { font-size: 13px; margin: 24px 0 8px; text-transform: uppercase; letter-spacing: 0.06em; color: #374151; }
  .muted { color: #6b7280; }
  .meta { text-align: right; line-height: 1.6; }
  .parties { display: flex; justify-content: space-between; gap: 24px; margin-top: 20px; line-height: 1.5; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th, td { padding: 8px; border-bottom: 1px solid #e5e7eb; text-align: left; vertical-align: top; }
  th { background: #f3f4f6; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; }
  .num { text-align: right; white-space: nowrap; }
  .totals { width: 320px; margin-left: auto; margin-top: 12px; }
  .totals td { border: 0; padding: 4px 8px; }
  .totals .grand td { border-top: 2px solid #111827; font-size: 15px; font-weight: 700; padding-top: 8px; }
  .due td { color: ${invoice.balance > 0 ? "#b91c1c" : "#15803d"}; font-weight: 700; }
  .words { margin-top: 12px; font-style: italic; }
  .stamp { display: inline-block; margin-top: 8px; padding: 2px 10px; border: 2px solid; border-radius: 4px; font-weight: 700; letter-spacing: 0.1em; }
  footer { margin-top: 40px; display: flex; justify-content: space-between; align-items: flex-end; font-size: 11px; }
  .sign { text-align: center; border-top: 1px solid #9ca3af; padding-top: 6px; width: 200px; }
  .toolbar { text-align: right; margin-bottom: 16px; }
  .toolbar button { font: inherit; padding: 8px 16px; border-radius: 6px; border: 1px solid #d1d5db; background: #111827; color: #fff; cursor: pointer; }
  @media print { body { padding: 0; } .toolbar { display: none; } @page { margin: 14mm; } }
</style>
</head>
<body>
<div class="sheet">
  <div class="toolbar"><button onclick="window.print()">Print / Save as PDF</button></div>
  <header>
    <div>
      <h1>${escapeHtml(merchant?.business_name ?? "")}</h1>
      ${merchantAddress.map((line) => `<div class="muted">${escapeHtml(line)}</div>`).join("")}
      ${merchant?.mobile_number ? `<div class="muted">Phone: ${escapeHtml(merchant.mobile_number)}</div>` : ""}
      ${merchant?.gst_number ? `<div><strong>GSTIN:</strong> ${escapeHtml(merchant.gst_number)}</div>` : ""}
    </div>
    <div class="meta">
      <h2>${escapeHtml(title)}</h2>
      <div><strong>No.</strong> ${escapeHtml(invoice.invoiceNumber)}</div>
      <div><strong>Date:</strong> ${date(invoice.issuedAt)}</div>
      <div><strong>Due:</strong> ${date(invoice.dueAt)}</div>
      <div><strong>Order:</strong> ${escapeHtml(invoice.orderNumber)}</div>
      <div class="stamp" style="color:${invoice.status === "PAID" ? "#15803d" : invoice.status === "PARTIAL" ? "#b45309" : "#b91c1c"}">${escapeHtml(invoice.status === "PARTIAL" ? "PART PAID" : invoice.status)}</div>
    </div>
  </header>

  <div class="parties">
    <div>
      <div class="muted">Bill to</div>
      <strong>${escapeHtml(invoice.customerName)}</strong>
      ${order?.deliverySiteName ? `<div>${escapeHtml(order.deliverySiteName)}</div>` : ""}
      ${billTo.map((line) => `<div>${escapeHtml(line)}</div>`).join("")}
      ${invoice.gstin ? `<div><strong>GSTIN:</strong> ${escapeHtml(invoice.gstin)}</div>` : ""}
    </div>
  </div>

  <table>
    <thead><tr><th>#</th><th>Description</th><th class="num">Qty</th><th class="num">Rate (incl. GST)</th><th class="num">Amount</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>

  <table class="totals">
    <tr><td>Taxable value</td><td class="num">${money(invoice.amount)}</td></tr>
    ${
      !invoice.gstAmount
        ? ""
        : interState
          ? `<tr><td>IGST (${invoice.gstPercent}%)</td><td class="num">${money(invoice.gstAmount)}</td></tr>`
          : `<tr><td>CGST (${invoice.gstPercent / 2}%)</td><td class="num">${money(invoice.gstAmount / 2)}</td></tr>
           <tr><td>SGST (${invoice.gstPercent / 2}%)</td><td class="num">${money(invoice.gstAmount / 2)}</td></tr>`
    }
    <tr class="grand"><td>Total</td><td class="num">${money(invoice.totalAmount)}</td></tr>
    <tr><td>Paid</td><td class="num">${money(invoice.paidAmount)}</td></tr>
    <tr class="due"><td>Balance due</td><td class="num">${money(invoice.balance)}</td></tr>
  </table>
  <div class="words">${escapeHtml(rupeesInWords(invoice.totalAmount))}</div>

  ${paymentRows}

  <footer>
    <div class="muted">Computer-generated invoice. Prices are inclusive of GST.<br/>Printed ${date(new Date().toISOString())}</div>
    <div class="sign">For ${escapeHtml(merchant?.business_name ?? "the supplier")}<br/>Authorised signatory</div>
  </footer>
</div>
</body>
</html>`);
  win.document.close();
  win.focus();
  return true;
}
