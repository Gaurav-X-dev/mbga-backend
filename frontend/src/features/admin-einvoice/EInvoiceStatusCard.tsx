import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getEInvoiceState, retryEInvoice } from "../../api/einvoice.api";
import { queryKeys } from "../../api/query-keys";

/**
 * One invoice's standing with the GST portal.
 *
 * Three things an operator needs and nothing else: whether it was filed, the government
 * references if it was, and - when it was not - the portal's own words about why.
 *
 * **The error is shown verbatim.** NIC names the field it rejected ("Buyer GSTIN is
 * invalid", "Pincode does not belong to the state"), and that sentence is the only thing
 * that turns this into a five-minute correction. Replacing it with "Something went wrong"
 * would send the accountant to support instead of to the customer record.
 */

const TONE: Record<string, { label: string; className: string }> = {
  DONE: { label: "Filed", className: "bg-green-50 text-green-700 border-green-200" },
  PENDING: { label: "Queued", className: "bg-blue-50 text-blue-700 border-blue-200" },
  FAILED: { label: "Rejected", className: "bg-red-50 text-red-700 border-red-200" },
  ABANDONED: { label: "Given up", className: "bg-amber-50 text-amber-800 border-amber-200" },
  SKIPPED: { label: "Not applicable", className: "bg-gray-50 text-gray-600 border-gray-200" }
};

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3 text-sm">
      <span className="w-40 shrink-0 text-gray-500">{label}</span>
      <span className="break-all font-mono text-gray-900">{value}</span>
    </div>
  );
}

export function EInvoiceStatusCard({ invoiceId }: { invoiceId: string }) {
  const queryClient = useQueryClient();

  const state = useQuery({
    queryKey: queryKeys.einvoice.state(invoiceId),
    queryFn: ({ signal }) => getEInvoiceState(invoiceId, signal),
    // A queued invoice is being worked on by someone else's process, so the screen refreshes
    // itself rather than making the operator press reload to find out.
    refetchInterval: (query) => (query.state.data?.status === "PENDING" ? 15_000 : false)
  });

  const retry = useMutation({
    mutationFn: () => retryEInvoice(invoiceId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.einvoice.all });
    }
  });

  if (state.isLoading) {
    return <p className="text-sm text-gray-500">Loading e-Invoice status…</p>;
  }
  if (state.isError || !state.data) {
    return <p className="text-sm text-red-600">e-Invoice status could not be loaded.</p>;
  }

  const data = state.data;

  // Never queued. This is the ordinary outcome for a domestic customer, not a failure, so it
  // says what the rule is rather than showing an empty compliance block.
  if (!data.status) {
    return (
      <p className="text-sm text-gray-600">
        No e-Invoice. The customer on this invoice has no GSTIN, so the sale is B2C and the
        portal does not accept it.
      </p>
    );
  }

  const tone = TONE[data.status] ?? TONE.SKIPPED;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${tone.className}`}>
          {tone.label}
        </span>
        {data.withEwayBill ? (
          <span className="rounded-full border border-gray-200 bg-gray-50 px-2.5 py-0.5 text-xs text-gray-700">
            e-Way Bill required (over ₹50,000)
          </span>
        ) : null}
        {data.attempts > 0 ? (
          <span className="text-xs text-gray-500">
            {data.attempts} attempt{data.attempts === 1 ? "" : "s"}
          </span>
        ) : null}
      </div>

      {data.irn ? (
        <div className="space-y-1">
          <Row label="IRN" value={data.irn} />
          {data.acknowledgementNumber ? (
            <Row label="Acknowledgement" value={data.acknowledgementNumber} />
          ) : null}
          {data.ewayBillNumber ? <Row label="e-Way Bill" value={data.ewayBillNumber} /> : null}
        </div>
      ) : null}

      {data.lastError ? (
        <div className="rounded-md border border-red-200 bg-red-50 p-3">
          <p className="text-xs font-medium text-red-800">The portal said:</p>
          <p className="mt-1 break-words text-sm text-red-700">{data.lastError}</p>
        </div>
      ) : null}

      {data.status === "PENDING" && !data.irn ? (
        <p className="text-sm text-gray-600">
          Queued. The filing worker picks this up within a minute; nothing else is needed.
        </p>
      ) : null}

      {data.canRetry ? (
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => retry.mutate()}
            disabled={retry.isPending}
            className="rounded-md bg-gray-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {retry.isPending ? "Queuing…" : "File again"}
          </button>
          <span className="text-xs text-gray-500">
            Correct the record the message names first — this re-sends the same document.
          </span>
        </div>
      ) : null}

      {retry.isError ? (
        <p className="text-sm text-red-600">Could not queue it again. Try once more.</p>
      ) : null}
    </div>
  );
}

export default EInvoiceStatusCard;
