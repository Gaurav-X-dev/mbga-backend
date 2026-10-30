import { apiClient } from "./client";

/**
 * GST e-Invoice filing, read and retried from the panel.
 *
 * The backend queues an invoice at handover and a worker files it; nothing here talks to the
 * portal. `retry` only clears the back-off, so a staff member pressing the button repeatedly
 * cannot turn one document into a burst of requests at the government.
 */

export type EInvoiceStatus = "PENDING" | "DONE" | "FAILED" | "ABANDONED" | "SKIPPED";

export type EInvoiceState = {
  /** Null when the invoice was never queued - a sale to a customer with no GSTIN is B2C. */
  status: EInvoiceStatus | null;
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

export type InvoiceSummary = {
  id: string;
  invoiceNumber: string;
  orderNumber: string;
  customerId: string;
  customerName: string;
  totalAmount: number;
  balance: number;
  status: string;
  issuedAt: string;
  isGstInvoice: boolean;
  gstin: string | null;
};

export async function listInvoices(signal?: AbortSignal) {
  return (await apiClient.get<InvoiceSummary[]>("/admin/invoices", { signal })).data;
}

export async function getEInvoiceState(invoiceId: string, signal?: AbortSignal) {
  return (
    await apiClient.get<EInvoiceState>(`/admin/invoices/${invoiceId}/einvoice`, { signal })
  ).data;
}

export async function retryEInvoice(invoiceId: string) {
  return (await apiClient.post<EInvoiceState>(`/admin/invoices/${invoiceId}/einvoice/retry`, {}))
    .data;
}
