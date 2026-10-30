import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getEInvoiceState, retryEInvoice } from "../../api/payments.api";
import { queryKeys } from "../../api/query-keys";
import { Button } from "../../components/common/Button";
import { Badge } from "../../components/common/StatusBadge";
import { Alert, LoadingSkeleton } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { DetailsPanel } from "../../components/layout/Page";
import { formatDateTime } from "../../utils/format";
import type { Tone } from "../../utils/labels";

/**
 * This invoice's standing with the GST portal.
 *
 * Two government rules decide what happens, and the backend applies both - this only reports
 * them. An IRN is obtained when the customer has a GSTIN, because a sale to an unregistered
 * buyer is B2C and the portal rejects it. An e-Way Bill is required once the consignment is
 * worth more than fifty thousand rupees, and that rule asks nothing about the customer - so
 * an unregistered buyer's large order is filed as an e-Way Bill on its own, with no IRN.
 * `withIrn` is what tells those apart, and the screen says which one is happening rather
 * than calling anything without an IRN "B2C".
 *
 * **The portal's error is shown word for word.** NIC names the field it rejected - "Buyer
 * GSTIN is invalid", "Pincode does not belong to the state" - and that sentence is what turns
 * this into a five-minute correction on the customer record. A friendly rewrite would send
 * the accountant to support instead.
 */

const FILING: Record<string, { label: string; tone: Tone }> = {
  DONE: { label: "Filed", tone: "success" },
  PENDING: { label: "Queued", tone: "info" },
  FAILED: { label: "Rejected", tone: "danger" },
  ABANDONED: { label: "Given up", tone: "warning" },
  SKIPPED: { label: "Not applicable", tone: "neutral" }
};

export function EInvoiceSection({ merchantId, invoiceId }: { merchantId: string; invoiceId: string }) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: queryKeys.payments.einvoice(merchantId, invoiceId),
    queryFn: ({ signal }) => getEInvoiceState(merchantId, invoiceId, signal),
    // A queued row is being worked on by a process nobody here can see, so the panel refreshes
    // itself rather than making the operator reload to find out it finished.
    refetchInterval: (q) => (q.state.data?.status === "PENDING" ? 15_000 : false)
  });

  const retry = useMutation({
    mutationFn: () => retryEInvoice(merchantId, invoiceId),
    onSuccess: () => {
      toast.success("Queued again. The filing worker will pick it up shortly.");
      void queryClient.invalidateQueries({ queryKey: queryKeys.payments.einvoice(merchantId, invoiceId) });
    },
    onError: () => toast.error("Could not queue it again.")
  });

  if (query.isLoading) return <LoadingSkeleton rows={2} label="Loading e-Invoice status" />;
  if (query.isError || !query.data) {
    return <p className="text-muted text-small">e-Invoice status could not be loaded.</p>;
  }

  const state = query.data;

  // Never queued, for one of two reasons that must not be confused. A B2C sale is settled -
  // it will never be filed. An eligible invoice with no job was raised before this existed,
  // or had its GSTIN added afterwards, and can still be filed - so it is offered, not
  // explained away. Saying "no GSTIN" about an invoice that has one would send an accountant
  // looking for a problem that is not there.
  if (!state.status) {
    if (!state.eligible) {
      return (
        <p className="text-muted text-small">
          Nothing to file. This customer has no GSTIN, so the sale is B2C and no IRN applies,
          and the invoice is under ₹50,000 so no e-Way Bill is required either.
        </p>
      );
    }
    return (
      <div className="stack" style={{ gap: 10 }}>
        <p className="text-muted text-small">
          Not filed yet. This invoice was raised before e-Invoicing was switched on, so it was
          never queued — it can be filed now.
        </p>
        <div className="row" style={{ gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <Button icon="refresh" onClick={() => retry.mutate()} loading={retry.isPending} loadingText="Queuing…">
            File now
          </Button>
        </div>
      </div>
    );
  }

  const meta = FILING[state.status] ?? FILING.SKIPPED;

  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <Badge tone={meta.tone}>{meta.label}</Badge>
        {state.withEwayBill ? <Badge tone="info">e-Way Bill required</Badge> : null}
        {/* Said plainly, because an operator seeing "Filed" with no IRN beside it would
            otherwise reasonably think something had gone missing. */}
        {!state.withIrn ? <Badge tone="neutral">Buyer unregistered — no IRN</Badge> : null}
        {state.attempts > 0 ? (
          <span className="text-muted text-small">
            {state.attempts} attempt{state.attempts === 1 ? "" : "s"}
          </span>
        ) : null}
      </div>

      {state.irn ? (
        <DetailsPanel
          items={[
            { label: "IRN", value: <span className="mono" style={{ wordBreak: "break-all" }}>{state.irn}</span> },
            { label: "Acknowledgement", value: state.acknowledgementNumber ? <span className="mono">{state.acknowledgementNumber}</span> : "—" },
            { label: "e-Way Bill", value: state.ewayBillNumber ? <span className="mono">{state.ewayBillNumber}</span> : "—" },
            { label: "Filed at", value: state.completedAt ? formatDateTime(state.completedAt) : "—" }
          ]}
        />
      ) : null}

      {state.lastError ? <Alert tone="error">The portal said: {state.lastError}</Alert> : null}

      {state.status === "PENDING" && !state.irn ? (
        <p className="text-muted text-small">
          Queued. The filing worker picks this up on its next pass; nothing else is needed.
          {state.nextAttemptAt ? ` Next attempt ${formatDateTime(state.nextAttemptAt)}.` : ""}
        </p>
      ) : null}

      {state.canRetry ? (
        <div className="row" style={{ gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <Button
            icon="refresh"
            onClick={() => retry.mutate()}
            loading={retry.isPending}
            loadingText="Queuing…"
          >
            File again
          </Button>
          <span className="text-muted text-small">
            Correct the record the message names first — this re-sends the same document.
          </span>
        </div>
      ) : null}
    </div>
  );
}
