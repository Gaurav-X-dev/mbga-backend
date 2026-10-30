import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { normalizeError } from "../../api/errors";
import { fetchPaymentProof, type Payment } from "../../api/payments.api";
import { queryKeys } from "../../api/query-keys";
import { Button } from "../../components/common/Button";
import { Alert, LoadingSkeleton } from "../../components/feedback/Feedback";

/**
 * The screenshot a customer or driver uploaded as evidence. A proof is not a reconciliation:
 * the payment stays PENDING until someone matches it against the bank statement.
 */
export function PaymentProof({ merchantId, payment }: { merchantId: string; payment: Payment }) {
  const [expanded, setExpanded] = useState(false);
  const query = useQuery({
    queryKey: queryKeys.payments.proof(merchantId, payment.id),
    queryFn: ({ signal }) => fetchPaymentProof(merchantId, payment, signal),
    enabled: Boolean(payment.proofUrl),
    staleTime: 10 * 60_000,
    retry: false
  });

  const blob = query.data;
  const url = useMemo(() => (blob ? URL.createObjectURL(blob) : null), [blob]);
  useEffect(() => () => (url ? URL.revokeObjectURL(url) : undefined), [url]);

  if (!payment.proofUrl) return <p className="text-muted text-small" style={{ margin: 0 }}>No proof was uploaded with this payment.</p>;
  if (query.isLoading) return <LoadingSkeleton rows={3} label="Loading proof" />;
  if (query.error) {
    const error = normalizeError(query.error);
    return (
      <Alert tone={error.status === 404 ? "info" : "error"}>
        {error.status === 404 ? "The proof file is not available any more." : error.status === 403 ? "You do not have permission to view payment proofs." : error.userMessage}{" "}
        {error.status !== 404 && error.status !== 403 ? (
          <button type="button" className="btn--link" onClick={() => void query.refetch()}>
            Retry
          </button>
        ) : null}
      </Alert>
    );
  }
  if (!url || !blob) return null;

  const isPdf = blob.type === "application/pdf";
  return (
    <div className="stack" style={{ gap: 8 }}>
      {isPdf ? (
        <iframe title={`Proof for ${payment.paymentNumber}`} src={url} style={{ width: "100%", height: 420, border: "1px solid var(--border)", borderRadius: 8 }} />
      ) : (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          title={expanded ? "Show smaller" : "Show full size"}
          style={{ padding: 0, border: "1px solid var(--border)", borderRadius: 8, background: "var(--surface-muted, #f8fafc)", cursor: "zoom-in", overflow: "hidden" }}
        >
          <img
            src={url}
            alt={`Payment proof for ${payment.paymentNumber}`}
            style={{ display: "block", width: "100%", maxHeight: expanded ? "none" : 360, objectFit: "contain" }}
          />
        </button>
      )}
      <div className="row" style={{ gap: 8 }}>
        <Button size="sm" variant="secondary" icon="eye" onClick={() => window.open(url, "_blank", "noopener")}>
          Open in new tab
        </Button>
        <a className="btn btn--secondary btn--sm" href={url} download={`${payment.paymentNumber}-proof${isPdf ? ".pdf" : ""}`}>
          Download
        </a>
      </div>
    </div>
  );
}
