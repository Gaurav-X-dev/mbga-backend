import { apiClient } from "./client";
import { cleanParams } from "./params";

/** Admin channel: /admin/invoices and /admin/payments. Merchant-scoped - `merchantId` on every call. */
export type InvoiceStatus = "UNPAID" | "PARTIAL" | "PAID";
export type PaymentMode = "ADVANCE" | "CASH" | "UPI" | "NEFT" | "SPLIT";
export type ReconciliationStatus = "PENDING" | "RECONCILED" | "INVALID";

export type Invoice = {
  id: string;
  invoiceNumber: string;
  orderId: string;
  orderNumber: string;
  customerId: string;
  customerName: string;
  amount: number;
  gstPercent: number;
  gstAmount: number;
  totalAmount: number;
  paidAmount: number;
  balance: number;
  status: InvoiceStatus;
  issuedAt: string;
  dueAt: string;
  isOverdue: boolean;
  isGstInvoice: boolean;
  gstin?: string | null;
};

export type Payment = {
  id: string;
  paymentNumber: string;
  invoiceId: string;
  invoiceNumber: string;
  customerId: string;
  customerName: string;
  invoiceAmount: number;
  amountCollected: number;
  mode: PaymentMode;
  cashAmount?: number;
  upiAmount?: number;
  effectiveAmount?: number;
  /** When the money changed hands, not when it was typed in. */
  paidAt: string;
  reference?: string | null;
  reconciliationStatus: ReconciliationStatus;
  invalidReason?: string | null;
  collectedBy?: string | null;
  customerRunningBalance: number;
  note?: string | null;
  /** Protected path to the uploaded screenshot, or null when none was uploaded. Fetch with the token. */
  proofUrl?: string | null;
};

export type InvoiceListParams = { merchantId: string; customerId?: string; openOnly?: boolean };

export type PaymentListParams = {
  merchantId: string;
  customerId?: string;
  /** A ReconciliationStatus or `ALL`. */
  reconciliationStatus?: string;
  search?: string;
};

export type RecordPaymentInput = {
  invoiceId: string;
  amount: number;
  mode: PaymentMode;
  cashAmount?: number;
  upiAmount?: number;
  effectiveAmount?: number;
  /** Required for UPI and NEFT - it is what the statement is matched against. */
  reference?: string;
  paidAt?: string;
  note?: string;
};

const scoped = (merchantId: string) => ({ params: { merchantId } });

export async function listInvoices(params: InvoiceListParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<Invoice[]>("/admin/invoices", { params: cleanParams(params), signal });
  return data;
}

export async function listPayments(params: PaymentListParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<Payment[]>("/admin/payments", { params: cleanParams(params), signal });
  return data;
}

export async function getPayment(merchantId: string, paymentId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<Payment>(`/admin/payments/${encodeURIComponent(paymentId)}`, {
    ...scoped(merchantId),
    signal
  });
  return data;
}

export async function recordPayment(merchantId: string, input: RecordPaymentInput) {
  const { data } = await apiClient.post<Payment>("/admin/payments", input, scoped(merchantId));
  return data;
}

/** `reconciled: false` marks it invalid, puts the money back on the invoice, and needs a reason. */
export async function reconcilePayment(merchantId: string, paymentId: string, reconciled: boolean, reason?: string) {
  const { data } = await apiClient.post<Payment>(
    `/admin/payments/${encodeURIComponent(paymentId)}/reconcile`,
    { reconciled, reason: reason || null },
    scoped(merchantId)
  );
  return data;
}

export async function getInvoice(merchantId: string, invoiceId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<Invoice>(`/admin/invoices/${encodeURIComponent(invoiceId)}`, {
    ...scoped(merchantId),
    signal
  });
  return data;
}

/** "MBGA/2026-27/0013" → "MBGA-2026-27-0013.pdf": invoice numbers carry slashes a filename cannot. */
export function invoicePdfName(invoiceNumber: string) {
  return `${invoiceNumber.replace(/[\\/:*?"<>|\s]+/g, "-").replace(/^-+|-+$/g, "") || "invoice"}.pdf`;
}

/**
 * The server-rendered PDF, fetched with the session (the endpoint is protected, so a plain link
 * would not carry the token). Refuses anything that is not a PDF, so an error page is never saved
 * to disk looking like a corrupted invoice.
 */
export async function fetchInvoicePdf(merchantId: string, invoiceId: string, invoiceNumber: string) {
  const response = await apiClient.get<Blob>(`/admin/invoices/${encodeURIComponent(invoiceId)}/document.pdf`, {
    ...scoped(merchantId),
    responseType: "blob",
    headers: { Accept: "application/pdf" },
    timeout: 60_000
  });
  const head = await response.data.slice(0, 5).text();
  if (head !== "%PDF-") throw new Error(`The server did not send a PDF (got ${response.data.type || "unknown type"}).`);
  const blob = new Blob([response.data], { type: "application/pdf" });
  return { blob, filename: invoicePdfName(invoiceNumber) };
}

export async function downloadInvoicePdf(merchantId: string, invoiceId: string, invoiceNumber: string) {
  const { blob, filename } = await fetchInvoicePdf(merchantId, invoiceId, invoiceNumber);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
  return filename;
}

/**
 * Shares the PDF through the device's share sheet where the browser supports sharing files
 * (most phones, Safari, Edge); elsewhere it downloads instead. Says which happened.
 */
export async function shareInvoicePdf(merchantId: string, invoiceId: string, invoiceNumber: string): Promise<"shared" | "downloaded" | "cancelled"> {
  const { blob, filename } = await fetchInvoicePdf(merchantId, invoiceId, invoiceNumber);
  const file = new File([blob], filename, { type: "application/pdf" });
  if (typeof navigator.canShare === "function" && navigator.canShare({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title: `Invoice ${invoiceNumber}` });
      return "shared";
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return "cancelled";
      throw error;
    }
  }
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
  return "downloaded";
}

/** The full invoice document as data (seller, buyer, lines, tax), for building a custom view. */
export async function getInvoiceDocument(merchantId: string, invoiceId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<Record<string, unknown>>(`/admin/invoices/${encodeURIComponent(invoiceId)}/document`, { ...scoped(merchantId), signal });
  return data;
}

/** The server-rendered invoice as HTML, for printing. Fetched with the session, so it cannot be a plain link. */
export async function getInvoiceHtml(merchantId: string, invoiceId: string) {
  const { data } = await apiClient.get<string>(`/admin/invoices/${encodeURIComponent(invoiceId)}/document.html`, {
    ...scoped(merchantId),
    responseType: "text"
  });
  return data;
}

/**
 * The payment's proof image as a blob, fetched with the session (the URL is protected, so it
 * cannot go straight into an <img>). Uses the `proofUrl` the API returned rather than building
 * one, and always sends the selected merchant, which the admin endpoint requires.
 */
export async function fetchPaymentProof(merchantId: string, payment: { id: string; proofUrl?: string | null }, signal?: AbortSignal) {
  let url = payment.proofUrl || `/admin/payments/${encodeURIComponent(payment.id)}/proof`;
  // The client's base URL already ends in /api/v1; a path that repeats it would double up.
  if (!/^https?:/i.test(url)) url = url.replace(/^\/?api\/v1(?=\/)/, "");
  const hasMerchant = /[?&]merchantId=/.test(url);
  const { data } = await apiClient.get<Blob>(url, {
    params: hasMerchant ? undefined : { merchantId },
    responseType: "blob",
    signal,
    timeout: 60_000
  });
  return data;
}

/**
 * GST e-Invoice filing (IRN / e-Way Bill).
 *
 * The backend queues an invoice at handover and a worker files it; nothing here talks to the
 * government portal. `retryEInvoice` only clears the back-off, so a staff member pressing the
 * button repeatedly cannot turn one document into a burst of requests at NIC.
 */
export type EInvoiceFilingStatus = "PENDING" | "DONE" | "FAILED" | "ABANDONED" | "SKIPPED";

export type EInvoiceState = {
  /**
   * Null when the invoice was never queued. Two different reasons, told apart by `eligible`:
   * a B2C sale that will never be filed, or an invoice raised before this existed.
   */
  status: EInvoiceFilingStatus | null;
  /** True when the buyer has a GSTIN, so an IRN applies to this invoice at all. */
  eligible: boolean;
  withEwayBill: boolean;
  attempts: number;
  /** The portal's own sentence. Shown verbatim: it names the field an accountant must fix. */
  lastError: string | null;
  nextAttemptAt: string | null;
  completedAt: string | null;
  irn: string | null;
  acknowledgementNumber: string | null;
  ewayBillNumber: string | null;
  canRetry: boolean;
};

export async function getEInvoiceState(merchantId: string, invoiceId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<EInvoiceState>(
    `/admin/invoices/${encodeURIComponent(invoiceId)}/einvoice`,
    { ...scoped(merchantId), signal }
  );
  return data;
}

export async function retryEInvoice(merchantId: string, invoiceId: string) {
  const { data } = await apiClient.post<EInvoiceState>(
    `/admin/invoices/${encodeURIComponent(invoiceId)}/einvoice/retry`,
    {},
    scoped(merchantId)
  );
  return data;
}
