import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { getKycApplication, type KycAddress } from "../../api/customer-kyc.api";
import { queryKeys } from "../../api/query-keys";
import { Button, ButtonLink } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { Badge, StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { Alert, ErrorState, LoadingSkeleton } from "../../components/feedback/Feedback";
import { Card, DetailsPanel, PageHeader } from "../../components/layout/Page";
import { formatDate, formatDateTime, formatRelativeTime, humanize } from "../../utils/format";
import { CustomerOrdersCard } from "./CustomerOrdersCard";
import { DocumentProgress } from "./DocumentProgress";
import { DocumentNumber } from "./DocumentNumber";
import { documentNumberKey as docKey, useDocumentNumbers } from "./useDocumentNumbers";
import { DocumentViewButton } from "./DocumentViewer";
import { KycDecisionDialogs, type KycDecisionTarget } from "./KycDecisionDialogs";

/*
 * One application, on its own page.
 *
 * A KYC record is the sort of thing a reviewer reads carefully, links to a colleague and
 * comes back to — so it gets an address of its own rather than a drawer that disappears on
 * a stray click and cannot be shared.
 *
 * The merchant is not in the response, and viewing a file needs it, so the queue passes it in
 * the link (`?merchant=`).
 */

function formatAddress(address: KycAddress | null | undefined) {
  if (!address) return null;
  return [address.line1, address.line2, address.city, address.state, address.pincode].filter(Boolean).join(", ") || null;
}

export function CustomerKycDetailPage() {
  const { applicationId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const merchantId = searchParams.get("merchant");
  const [decision, setDecision] = useState<KycDecisionTarget | null>(null);
  const { canReveal, shownNumbers, fullNumbers, loading, errors, toggleNumber, showAll, hideAll } = useDocumentNumbers(applicationId);
  const query = useQuery({
    queryKey: queryKeys.customerKyc.detail(applicationId),
    queryFn: ({ signal }) => getKycApplication(applicationId, signal),
    enabled: Boolean(applicationId)
  });

  if (query.isLoading) {
    return (
      <div className="page">
        <PageHeader title="Customer application" documentTitle="Customer application" />
        <Card>
          <LoadingSkeleton rows={6} label="Loading the application" />
        </Card>
      </div>
    );
  }

  if (query.error || !query.data) {
    return (
      <div className="page">
        <PageHeader title="Customer application" documentTitle="Customer application" />
        <Card>
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        </Card>
      </div>
    );
  }

  const application = query.data;
  const documents = application.documents ?? [];
  const sites = application.sites ?? [];
  const customerId = searchParams.get("customer") ?? application.customerId;
  const allShown = documents.length > 0 && documents.every(document => shownNumbers.has(docKey(document)));
  const verified = documents.filter((document) => document.status?.toUpperCase() === "VERIFIED").length;
  const name = application.businessName || application.ownerName || application.mobile || "Customer application";
  const pending = application.status?.toUpperCase() === "PENDING";
  const decide = (kind: "approve" | "reject") =>
    merchantId && setDecision({ merchantId, customerId: application.customerId, name, decision: kind });
  const customerHref = merchantId
    ? `/admin/customer-accounts/${encodeURIComponent(application.customerId)}?merchant=${encodeURIComponent(merchantId)}`
    : null;

  return (
    <div className="page">
      <PageHeader
        title={name}
        documentTitle={name}
        eyebrow="Customer KYC"
        description={application.customerType ? humanize(application.customerType) : undefined}
        meta={
          <>
            <StatusBadge status={application.status} />
            <Badge tone="neutral">{application.id}</Badge>
            <span className="meta">Submitted {formatRelativeTime(application.submittedAt)}</span>
          </>
        }
        actions={
          <>
            {customerHref ? (
              <ButtonLink to={customerHref} variant="secondary" icon="users">
                Open customer
              </ButtonLink>
            ) : null}
            <ButtonLink to="/admin/customers" variant="secondary" icon="arrowLeft">
              Back to queue
            </ButtonLink>
            {pending ? (
              <>
                <Button variant="danger" icon="xCircle" onClick={() => decide("reject")} disabled={!merchantId}>
                  Reject
                </Button>
                <Button icon="checkCircle" onClick={() => decide("approve")} disabled={!merchantId}>
                  Approve
                </Button>
              </>
            ) : null}
          </>
        }
      />

      {pending && !merchantId ? (
        <Alert tone="info">Open this application from the KYC queue to approve or reject it.</Alert>
      ) : pending && documents.length && verified < documents.length ? (
        <Alert tone="warning" title="Check the documents before deciding">
          View each file below and confirm the numbers and names match the registration.
        </Alert>
      ) : null}

      {application.rejectionReason ? (
        <Alert tone="error" title="Rejected">
          {application.rejectionReason}
        </Alert>
      ) : null}

      <div className="grid-sidebar">
        <div className="stack-lg">
          <Card title="Customer information" subtitle="As submitted with this application">
            <div className="row" style={{ marginBottom: "var(--space-5)", flexWrap: "nowrap" }}>
              <UserAvatar name={name} size="lg" />
              <div className="cell-stack">
                <strong>{name}</strong>
                <small>{application.customerType ? humanize(application.customerType) : "Customer"}</small>
              </div>
            </div>
            <DetailsPanel
              items={[
                { label: "Business name", value: application.businessName || null },
                { label: "Owner name", value: application.ownerName || null },
                { label: "Mobile number", value: application.mobile },
                { label: "Email address", value: application.email || null },
                { label: "Connection type", value: application.customerType ? humanize(application.customerType) : null },
                { label: "Delivery address", value: formatAddress(application.deliveryAddress) }
              ]}
            />
          </Card>

          <Card
            title="Uploaded documents"
            subtitle="What the customer submitted for verification"
            actions={
              <span className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
                {documents.length ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={allShown ? "lock" : "eye"}
                    disabled={loading.size > 0}
                    onClick={() => allShown ? hideAll() : void showAll(documents)}
                  >
                    {allShown ? "Hide all numbers" : "Show all numbers"}
                  </Button>
                ) : null}
                <DocumentProgress verified={verified} total={documents.length} />
              </span>
            }
          >
            {documents.length === 0 ? (
              <p className="text-small text-muted">No documents were uploaded with this application.</p>
            ) : (
              <>
                {!merchantId ? (
                  <Alert tone="info">Open this application from the KYC queue to view the files.</Alert>
                ) : null}
                <p className="meta">{canReveal ? "Use Show number or Show all numbers to load the full IDs for verification." : "Document numbers are masked for your role. Use View to inspect the uploaded document."}</p>
                <ul className="doc-list list-plain">
                  {documents.map((document) => {
                    const files = document.files && document.files.length > 0
                      ? document.files
                      : document.fileId
                      ? [{ fileId: document.fileId, fileName: document.fileName ?? null, side: "FRONT" }]
                      : [];

                    return (
                      <li key={docKey(document)} className="doc-item">
                        <span className="doc-item__icon" aria-hidden="true">
                          <Icon name="fileText" size={16} />
                        </span>
                        <span className="doc-item__text" style={{ minWidth: 0 }}>
                          <strong>{humanize(document.type)}</strong>
                          <DocumentNumber value={canReveal ? fullNumbers[docKey(document)] || document.numberMasked : document.numberMasked}
                            shown={shownNumbers.has(docKey(document))} disabled={loading.has(docKey(document))}
                            onToggle={() => void toggleNumber(document)} />
                          {loading.has(docKey(document)) ? <span className="meta" role="status">Loading number…</span> : null}
                          {errors[docKey(document)] ? <Alert tone="error">{errors[docKey(document)]}</Alert> : null}
                          <span
                            title={document.fileName ?? undefined}
                            style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 360 }}
                          >
                            {document.fileName ?? (files.length > 0 ? `${files.length} file(s) attached` : "No file name")}
                            {document.uploadedAt ? ` · uploaded ${formatDateTime(document.uploadedAt)}` : ""}
                          </span>
                        </span>
                        <span className="row" style={{ gap: 8, flexWrap: "wrap", marginLeft: "auto", alignItems: "center" }}>
                          <StatusBadge status={document.status} />
                          {files.length === 0 ? (
                            <span className="text-small text-muted">No file</span>
                          ) : (
                            files.map((f, fIdx) => (
                              <DocumentViewButton
                                key={f.fileId || fIdx}
                                merchantId={merchantId}
                                document={{
                                  fileId: f.fileId,
                                  fileName: f.fileName,
                                  label: `${humanize(document.type)} ${f.side ? `(${humanize(f.side)})` : `Part ${fIdx + 1}`}`
                                }}
                                buttonText={files.length > 1 ? (f.side ? humanize(f.side) : `Part ${fIdx + 1}`) : "View"}
                              />
                            ))
                          )}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </>
            )}
          </Card>

          <CustomerOrdersCard merchantId={merchantId} customerId={customerId} />

          {sites.length > 0 ? (
            <Card title="Delivery sites" subtitle="Where this customer takes delivery">
              <ul className="doc-list list-plain">
                {sites.map((site) => (
                  <li key={site.id} className="doc-item">
                    <span className="doc-item__icon" aria-hidden="true">
                      <Icon name="mapPin" size={16} />
                    </span>
                    <span className="doc-item__text">
                      <strong>
                        {site.name}
                        {site.isPrimary ? " · Primary" : ""}
                      </strong>
                      <span>{formatAddress(site.address) ?? "No address recorded"}</span>
                      {site.contactName || site.contactMobile ? <span>{[site.contactName, site.contactMobile].filter(Boolean).join(" · ")}</span> : null}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </div>

        <div className="stack-lg">
          <Card title="Review" subtitle="Decision and who made it">
            <DetailsPanel
              columns={1}
              items={[
                { label: "Status", value: <StatusBadge status={application.status} /> },
                { label: "Submitted", value: formatDateTime(application.submittedAt) },
                { label: "Reviewed", value: application.reviewedAt ? formatDateTime(application.reviewedAt) : null },
                { label: "Reviewed by", value: application.reviewedBy || null },
                { label: "Reason given", value: application.rejectionReason || null }
              ]}
            />
          </Card>

          <Card title="Who decides this" subtitle="Usually the merchant; head office can step in">
            <p className="text-small text-muted">
              The merchant that holds this customer normally reviews the application. Head office can approve or
              reject it here too, for example when a merchant's queue is backing up. Only one decision is recorded.
            </p>
            {merchantId ? (
              <div style={{ marginTop: "var(--space-4)" }}>
                <ButtonLink to={`/admin/merchants/${encodeURIComponent(merchantId)}`} variant="secondary" icon="store">
                  Open merchant
                </ButtonLink>
              </div>
            ) : null}
          </Card>

          <Card title="Timeline" subtitle="What happened, in order">
            <ol className="timeline list-plain">
              <li>
                <time dateTime={application.submittedAt}>{formatDate(application.submittedAt)}</time>
                Application submitted
              </li>
              {application.reviewedAt ? (
                <li>
                  <time dateTime={application.reviewedAt}>{formatDate(application.reviewedAt)}</time>
                  {humanize(application.status)} by {application.reviewedBy ?? "a reviewer"}
                </li>
              ) : (
                <li>
                  <time>Now</time>
                  Waiting for the merchant to review
                </li>
              )}
            </ol>
          </Card>
        </div>
      </div>
      <KycDecisionDialogs target={decision} onClose={() => setDecision(null)} />
    </div>
  );
}
