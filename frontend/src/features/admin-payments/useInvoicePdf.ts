import { useState } from "react";

import { downloadInvoicePdf, shareInvoicePdf } from "../../api/payments.api";
import { useToast } from "../../components/feedback/toast-context";

type InvoiceRef = { id: string; invoiceNumber: string };

/** Download / share the server PDF of an invoice, with the toasts every screen shows. */
export function useInvoicePdf(merchantId: string) {
  const toast = useToast();
  const [busy, setBusy] = useState<{ id: string; action: "download" | "share" } | null>(null);

  async function run(invoice: InvoiceRef, action: "download" | "share") {
    setBusy({ id: invoice.id, action });
    try {
      if (action === "download") {
        const name = await downloadInvoicePdf(merchantId, invoice.id, invoice.invoiceNumber);
        toast.success(`Downloaded ${name}.`);
      } else {
        const result = await shareInvoicePdf(merchantId, invoice.id, invoice.invoiceNumber);
        if (result === "downloaded") toast.success(`This browser cannot share files, so ${invoice.invoiceNumber} was downloaded instead.`);
      }
    } catch (error) {
      console.error(`Invoice PDF ${action} failed`, error);
      toast.error(`The PDF for ${invoice.invoiceNumber} could not be ${action === "download" ? "downloaded" : "shared"}. Try again.`);
    } finally {
      setBusy(null);
    }
  }

  return {
    download: (invoice: InvoiceRef) => run(invoice, "download"),
    share: (invoice: InvoiceRef) => run(invoice, "share"),
    isBusy: (invoiceId: string, action?: "download" | "share") => Boolean(busy && busy.id === invoiceId && (!action || busy.action === action))
  };
}
