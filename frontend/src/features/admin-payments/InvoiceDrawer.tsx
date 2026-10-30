import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { getMerchant } from "../../api/merchants.api";
import { getOrder } from "../../api/orders.api";
import { getInvoice, getInvoiceHtml, listPayments, type Invoice } from "../../api/payments.api";
import { queryKeys } from "../../api/query-keys";
import { Button } from "../../components/common/Button";
import { Badge } from "../../components/common/StatusBadge";
import { Drawer, DrawerSection } from "../../components/feedback/Dialogs";
import { Alert, ErrorState, LoadingSkeleton } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { DetailsPanel } from "../../components/layout/Page";
import { formatCurrency, formatDate, formatNumber } from "../../utils/format";
import type { Tone } from "../../utils/labels";
import { EInvoiceSection } from "./EInvoiceSection";
import { printInvoice, rupeesInWords } from "./print-invoice";
import { useInvoicePdf } from "./useInvoicePdf";

const STATUS: Record<string, { label: string; tone: Tone }> = {
  UNPAID: { label: "Unpaid", tone: "danger" },
  PARTIAL: { label: "Part paid", tone: "warning" },
  PAID: { label: "Paid", tone: "success" }
};

const RECON: Record<string, { label: string; tone: Tone }> = {
  PENDING: { label: "Pending check", tone: "warning" },
  RECONCILED: { label: "Reconciled", tone: "success" },
  INVALID: { label: "Invalid", tone: "danger" }
};

export function InvoiceDrawer({
  merchantId,
  invoiceId,
  onClose,
  onRecordPayment,
  onOpenPayment
}: {
  merchantId: string;
  invoiceId: string;
  onClose: () => void;
  onRecordPayment: (invoice: Invoice) => void;
  onOpenPayment: (paymentId: string) => void;
}) {
  const toast = useToast();
  const query = useQuery({
    queryKey: queryKeys.payments.invoice(merchantId, invoiceId),
    queryFn: ({ signal }) => getInvoice(merchantId, invoiceId, signal)
  });
  const invoice = query.data;

  // Line items live on the order; payments are matched by invoice number.
  const order = useQuery({
    queryKey: queryKeys.orders.detail(merchantId, invoice?.orderId ?? ""),
    queryFn: ({ signal }) => getOrder(merchantId, invoice!.orderId, signal),
    enabled: Boolean(invoice?.orderId),
    retry: false
  });
  const paymentParams = { merchantId, customerId: invoice?.customerId, reconciliationStatus: "ALL" };
  const payments = useQuery({
    queryKey: queryKeys.payments.list(paymentParams),
    queryFn: ({ signal }) => listPayments(paymentParams, signal),
    enabled: Boolean(invoice),
    retry: false
  });
  const merchant = useQuery({
    queryKey: queryKeys.merchants.detail(merchantId),
    queryFn: ({ signal }) => getMerchant(merchantId, signal),
    staleTime: 10 * 60_000,
    retry: false
  });

  const invoicePayments = (payments.data ?? []).filter((p) => p.invoiceId === invoiceId);
  const meta = invoice ? (STATUS[invoice.status] ?? { label: invoice.status, tone: "neutral" as Tone }) : null;
  const paidPct = invoice && invoice.totalAmount > 0 ? Math.min(100, (invoice.paidAmount / invoice.totalAmount) * 100) : 0;

  const [busy, setBusy] = useState<"print" | null>(null);
  const pdf = useInvoicePdf(merchantId);

  async function print() {
    if (!invoice) return;
    // Open the window now, while the click still counts as a user action, or pop-up blockers stop it.
    const win = window.open("", "_blank");
    if (!win) {
      toast.error("Allow pop-ups for this site to print the invoice.");
      return;
    }
    win.opener = null;
    setBusy("print");
    try {
      const html = await getInvoiceHtml(merchantId, invoice.id);
      win.document.open();
      win.document.write(html);
      win.document.close();
      // Give images and fonts a moment, then print once.
      setTimeout(() => win.print(), 600);
    } catch {
      // Server copy unavailable: fall back to the invoice built in the browser.
      win.close();
      const opened = printInvoice({ invoice, order: order.data, merchant: merchant.data, payments: invoicePayments });
      if (!opened) toast.error("Allow pop-ups for this site to print the invoice.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Drawer
      open
      size="lg"
      title={invoice?.invoiceNumber ?? "Invoice"}
      subtitle={invoice ? `${invoice.customerName} · issued ${formatDate(invoice.issuedAt)}` : undefined}
      meta={
        invoice && meta ? (
          <span className="row" style={{ gap: 6 }}>
            <Badge tone={meta.tone}>{meta.label}</Badge>
            {invoice.isOverdue && invoice.balance > 0 ? <Badge tone="danger">Overdue</Badge> : null}
            {invoice.isGstInvoice ? <Badge tone="info">GST invoice</Badge> : null}
          </span>
        ) : undefined
      }
      onClose={onClose}
      footer={
        invoice ? (
          <>
            <Button variant="secondary" icon="download" onClick={() => void pdf.download(invoice)} loading={pdf.isBusy(invoice.id, "download")} loadingText="Downloading…">
              Download PDF
            </Button>
            <Button variant="secondary" icon="send" onClick={() => void pdf.share(invoice)} loading={pdf.isBusy(invoice.id, "share")} loadingText="Preparing…">
              Share PDF
            </Button>
            <Button variant="secondary" icon="fileText" onClick={() => void print()} loading={busy === "print"} loadingText="Opening…">
              Print
            </Button>
            {invoice.balance > 0 ? (
              <Button icon="wallet" onClick={() => onRecordPayment(invoice)}>
                Record payment
              </Button>
            ) : null}
          </>
        ) : undefined
      }
    >
      {query.isLoading ? (
        <LoadingSkeleton rows={6} label="Loading invoice" />
      ) : query.error || !invoice ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          {invoice.isOverdue && invoice.balance > 0 ? (
            <Alert tone="error" title="Overdue">
              {formatCurrency(invoice.balance)} was due on {formatDate(invoice.dueAt)}.
            </Alert>
          ) : null}

          <DrawerSection title="Amount">
            <div className="stack" style={{ gap: 6 }}>
              <div className="row-between">
                <span className="text-muted text-small">
                  {formatCurrency(invoice.paidAmount)} paid of {formatCurrency(invoice.totalAmount)}
                </span>
                <strong>{Math.round(paidPct)}%</strong>
              </div>
              <span style={{ display: "block", height: 8, borderRadius: 999, background: "var(--border)" }}>
                <span
                  style={{
                    display: "block",
                    height: "100%",
                    width: `${paidPct}%`,
                    borderRadius: 999,
                    background: paidPct >= 100 ? "var(--green-500, #16a34a)" : "var(--blue-500, #3b82f6)"
                  }}
                />
              </span>
            </div>
            <DetailsPanel
              items={[
                { label: "Taxable value", value: formatCurrency(invoice.amount) },
                { label: `GST (${invoice.gstPercent}%)`, value: formatCurrency(invoice.gstAmount) },
                { label: "Total", value: <strong>{formatCurrency(invoice.totalAmount)}</strong> },
                { label: "Paid", value: formatCurrency(invoice.paidAmount) },
                {
                  label: "Balance due",
                  value: <strong style={{ color: invoice.balance > 0 ? "var(--red-600, #dc2626)" : "var(--green-600, #16a34a)" }}>{formatCurrency(invoice.balance)}</strong>
                },
                { label: "In words", value: <small>{rupeesInWords(invoice.totalAmount)}</small> }
              ]}
            />
          </DrawerSection>

          <DrawerSection title="Details">
            <DetailsPanel
              items={[
                { label: "Customer", value: invoice.customerName },
                { label: "Customer GSTIN", value: invoice.gstin ? <span className="mono">{invoice.gstin}</span> : "—" },
                {
                  label: "Order",
                  value: (
                    <Link to={`/admin/orders?merchant=${encodeURIComponent(merchantId)}&status=ALL&search=${encodeURIComponent(invoice.orderNumber)}`}>
                      {invoice.orderNumber}
                    </Link>
                  )
                },
                { label: "Issued", value: formatDate(invoice.issuedAt) },
                { label: "Due", value: formatDate(invoice.dueAt) }
              ]}
            />
          </DrawerSection>

          <DrawerSection title="e-Invoice (GST)">
            <EInvoiceSection merchantId={merchantId} invoiceId={invoice.id} />
          </DrawerSection>

          <DrawerSection title="Items">
            {order.isLoading ? (
              <LoadingSkeleton rows={3} label="Loading items" />
            ) : !order.data?.items?.length ? (
              <p className="text-muted text-small">Line items are not available for this order.</p>
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Cylinder</th>
                      <th style={{ textAlign: "right" }}>Qty</th>
                      <th style={{ textAlign: "right" }}>Rate (incl. GST)</th>
                      <th style={{ textAlign: "right" }}>Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {order.data.items.map((item) => (
                      <tr key={item.cylinderType}>
                        <td>{item.cylinderLabel}</td>
                        <td style={{ textAlign: "right" }}>{formatNumber(item.quantity)}</td>
                        <td style={{ textAlign: "right" }}>{formatCurrency(item.unitPrice)}</td>
                        <td style={{ textAlign: "right" }}>{formatCurrency(item.lineTotal)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </DrawerSection>

          <DrawerSection title={`Payments${invoicePayments.length ? ` (${invoicePayments.length})` : ""}`}>
            {payments.isLoading ? (
              <LoadingSkeleton rows={2} label="Loading payments" />
            ) : !invoicePayments.length ? (
              <p className="text-muted text-small">No payments recorded against this invoice yet.</p>
            ) : (
              <ul className="list-plain stack" style={{ gap: 8 }}>
                {invoicePayments.map((p) => {
                  const recon = RECON[p.reconciliationStatus] ?? { label: p.reconciliationStatus, tone: "neutral" as Tone };
                  return (
                    <li key={p.id} className="row-between" style={{ gap: 8 }}>
                      <span className="cell-stack">
                        <button type="button" className="btn--link" onClick={() => onOpenPayment(p.id)}>
                          {p.paymentNumber}
                        </button>
                        <small>
                          {formatDate(p.paidAt)} · {p.mode}
                          {p.reference ? ` · ${p.reference}` : ""}
                        </small>
                      </span>
                      <span className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
                        <Badge tone={recon.tone}>{p.mode === "SPLIT" ? `UPI: ${recon.label}` : recon.label}</Badge>
                        <strong className="nowrap" style={p.reconciliationStatus === "INVALID" && p.mode !== "SPLIT" ? { textDecoration: "line-through" } : undefined}>
                          {formatCurrency(p.mode === "SPLIT" && p.reconciliationStatus === "INVALID" ? p.cashAmount ?? 0 : p.amountCollected)}
                        </strong>
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </DrawerSection>
        </>
      )}
    </Drawer>
  );
}
