import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { getDocumentUrl } from "../../api/customers.api";
import { env } from "../../config/env";
import { Button } from "../../components/common/Button";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert, ErrorState, LoadingSkeleton } from "../../components/feedback/Feedback";

type ViewerDocument = { fileId?: string | null; fileName?: string | null; label: string };

/**
 * The signed link may come back as a path ("/api/v1/...") rather than a full URL. A path would
 * resolve against this panel's host, not the API's, so it is anchored to the API origin.
 */
function absolute(url: string) {
  try {
    return new URL(url, new URL(env.apiBaseUrl).origin).toString();
  } catch {
    return url;
  }
}

function kindOf(name: string | null | undefined): "image" | "pdf" | "other" {
  const ext = (name ?? "").split(".").pop()?.toLowerCase() ?? "";
  if (["jpg", "jpeg", "png", "gif", "webp"].includes(ext)) return "image";
  if (ext === "pdf") return "pdf";
  return "other";
}

/**
 * "View" button plus an in-page preview. The link expires within minutes, so it is fetched only
 * when the preview opens and never cached past it.
 */
export function DocumentViewButton({
  merchantId,
  document,
  buttonText = "View"
}: {
  merchantId: string | null;
  document: ViewerDocument;
  buttonText?: string;
}) {
  const [open, setOpen] = useState(false);
  if (!document.fileId) return <span className="text-small text-muted">No file</span>;
  return (
    <>
      <Button
        variant="secondary"
        size="sm"
        icon="eye"
        onClick={() => setOpen(true)}
        disabled={!merchantId}
        title={merchantId ? `View ${document.fileName ?? document.label}` : "Open this application from the KYC list to view files"}
      >
        {buttonText}
      </Button>
      {open && merchantId ? <DocumentPreview merchantId={merchantId} document={document} onClose={() => setOpen(false)} /> : null}
    </>
  );
}

function DocumentPreview({ merchantId, document, onClose }: { merchantId: string; document: ViewerDocument; onClose: () => void }) {
  const fileId = document.fileId!;
  const query = useQuery({
    queryKey: ["admin", "documents", "url", merchantId, fileId],
    queryFn: () => getDocumentUrl(merchantId, fileId),
    gcTime: 0,
    staleTime: 0,
    retry: false
  });
  const url = query.data ? absolute(query.data.url) : null;
  const kind = kindOf(document.fileName);
  const [failed, setFailed] = useState(false);

  return (
    <Modal
      open
      wide
      title={document.label}
      description={document.fileName ?? undefined}
      onClose={onClose}
      footer={
        <>
          {url ? (
            <a className="btn btn--secondary" href={url} target="_blank" rel="noreferrer noopener">
              Open in new tab
            </a>
          ) : null}
          <Button onClick={onClose}>Close</Button>
        </>
      }
    >
      {query.isLoading ? (
        <LoadingSkeleton rows={6} label="Loading document" />
      ) : query.error || !url ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} title="The document could not be opened" />
      ) : failed ? (
        <Alert tone="warning" title="The preview did not load">
          The link may have expired.{" "}
          <button
            type="button"
            className="btn--link"
            onClick={() => {
              setFailed(false);
              void query.refetch();
            }}
          >
            Try again
          </button>{" "}
          or use “Open in new tab”.
        </Alert>
      ) : kind === "image" ? (
        <div style={{ display: "flex", justifyContent: "center", background: "var(--surface-muted, #f3f4f6)", borderRadius: 8, padding: 8 }}>
          <img
            src={url}
            alt={`${document.label} document`}
            onError={() => setFailed(true)}
            style={{ maxWidth: "100%", maxHeight: "70vh", objectFit: "contain", borderRadius: 4 }}
          />
        </div>
      ) : kind === "pdf" ? (
        <iframe title={`${document.label} document`} src={url} style={{ width: "100%", height: "70vh", border: 0, borderRadius: 8 }} />
      ) : (
        <Alert tone="info">This file type cannot be previewed here. Use “Open in new tab” to download it.</Alert>
      )}
      {query.data ? <p className="meta" style={{ marginTop: "var(--space-3)" }}>This link expires in about {Math.max(1, Math.round(query.data.expiresInSeconds / 60))} minutes.</p> : null}
    </Modal>
  );
}
