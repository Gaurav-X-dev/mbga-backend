import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import type { ReactNode } from "react";

import { getKycApplication, type KycDocument } from "../../api/customer-kyc.api";
import { queryKeys } from "../../api/query-keys";
import { ButtonLink } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { Badge, StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { ErrorState, LoadingSkeleton } from "../../components/feedback/Feedback";
import { Card, DetailsPanel, PageHeader } from "../../components/layout/Page";
import { formatDate, formatDateTime, formatRelativeTime } from "../../utils/format";
import { humanize } from "../../utils/format";
import { DocumentProgress } from "./DocumentProgress";

/*
 * One application, on its own page.
 *
 * A KYC record is the sort of thing a reviewer reads carefully, links to a colleague and
 * comes back to — so it gets an address of its own rather than a drawer that disappears on
 * a stray click and cannot be shared.
 *
 * The response is the merchant reviewer's shape, so the customer object is read defensively:
 * the backend owns that contract and this page only surfaces what it finds.
 */

function text(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "string") return value.trim() || null;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return null;
}

/** First non-empty value among several possible key spellings. */
function pick(source: Record<string, unknown> | null | undefined, ...keys: string[]): string | null {
  if (!source) return null;
  for (const key of keys) {
    const value = text(source[key]);
    if (value) return value;
  }
  return null;
}

function documentStatus(document: KycDocument): string {
  return text(document.status) ?? "UPLOADED";
}

function documentLabel(document: KycDocument): string {
  const type = text(document.document_type);
  return type ? humanize(type) : "Document";
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="details__item">
      <dt className="details__label">{label}</dt>
      <dd className="details__value">{value ?? <span className="details__empty">Not provided</span>}</dd>
    </div>
  );
}

export function CustomerKycDetailPage() {
  const { applicationId = "" } = useParams();
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
  const customer = (application.customer ?? {}) as Record<string, unknown>;
  const documents = application.documents ?? [];
  const sites = application.delivery_sites ?? [];
  const verified = documents.filter((document) => documentStatus(document).toUpperCase() === "VERIFIED").length;

  const name = pick(customer, "business_name", "name", "full_name", "owner_name") ?? "Customer application";
  const mobile = pick(customer, "mobile_number", "mobile");
  const address =
    [
      pick(customer, "address_line1", "address_line_1"),
      pick(customer, "address_line2", "address_line_2"),
      [pick(customer, "address_city", "city"), pick(customer, "address_state", "state")].filter(Boolean).join(", "),
      pick(customer, "address_pincode", "pincode", "postal_code")
    ]
      .filter(Boolean)
      .join(", ") || null;

  return (
    <div className="page">
      <PageHeader
        title={name}
        documentTitle={name}
        eyebrow="Customer KYC"
        description={pick(customer, "customer_type") ?? undefined}
        meta={
          <>
            <StatusBadge status={application.status} />
            <Badge tone="neutral">{application.id}</Badge>
            <span className="meta">Submitted {formatRelativeTime(application.submitted_at)}</span>
          </>
        }
        actions={
          <ButtonLink to="/admin/customers" variant="secondary" icon="arrowLeft">
            Back to queue
          </ButtonLink>
        }
      />

      <div className="grid-sidebar">
        <div className="stack-lg">
          <Card title="Customer information" subtitle="As submitted with this application">
            <div className="row" style={{ marginBottom: "var(--space-5)", flexWrap: "nowrap" }}>
              <UserAvatar name={name} size="lg" />
              <div className="cell-stack">
                <strong>{name}</strong>
                <small>{pick(customer, "code") ?? "No customer code"}</small>
              </div>
            </div>
            <dl className="details">
              <Row label="Mobile number" value={mobile} />
              <Row label="Email address" value={pick(customer, "email")} />
              <Row label="Owner name" value={pick(customer, "owner_name")} />
              <Row label="GST number" value={pick(customer, "gst_number")} />
              <Row label="Connection type" value={pick(customer, "customer_type")} />
              <Row label="Pricing tier" value={pick(customer, "pricing_tier")} />
              <Row label="Account status" value={pick(customer, "status")} />
              <Row label="KYC status" value={pick(customer, "kyc_status")} />
            </dl>
            <div style={{ marginTop: "var(--space-5)" }}>
              <dl className="details details--single">
                <Row label="Address" value={address} />
              </dl>
            </div>
          </Card>

          <Card
            title="Uploaded documents"
            subtitle="What the customer submitted for verification"
            actions={<DocumentProgress verified={verified} total={documents.length} />}
          >
            {documents.length === 0 ? (
              <p className="text-small text-muted">No documents were uploaded with this application.</p>
            ) : (
              <ul className="doc-list list-plain">
                {documents.map((document, index) => (
                  <li key={text(document.id) ?? index} className="doc-item">
                    <span className="doc-item__icon" aria-hidden="true">
                      <Icon name="fileText" size={16} />
                    </span>
                    <span className="doc-item__text">
                      <strong>{documentLabel(document)}</strong>
                      <span>
                        {pick(document as Record<string, unknown>, "file_name", "number_masked") ?? "No file name"}
                      </span>
                    </span>
                    <StatusBadge status={documentStatus(document)} />
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {sites.length > 0 ? (
            <Card title="Delivery sites" subtitle="Where this customer takes delivery">
              <ul className="doc-list list-plain">
                {sites.map((site, index) => {
                  const record = site as Record<string, unknown>;
                  return (
                    <li key={text(record.id) ?? index} className="doc-item">
                      <span className="doc-item__icon" aria-hidden="true">
                        <Icon name="mapPin" size={16} />
                      </span>
                      <span className="doc-item__text">
                        <strong>{pick(record, "label", "name") ?? `Site ${index + 1}`}</strong>
                        <span>
                          {[
                            pick(record, "address_line1", "address_line_1"),
                            pick(record, "address_city", "city"),
                            pick(record, "address_pincode", "pincode")
                          ]
                            .filter(Boolean)
                            .join(", ") || "No address recorded"}
                        </span>
                      </span>
                    </li>
                  );
                })}
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
                { label: "Submitted", value: formatDateTime(application.submitted_at) },
                { label: "Reviewed", value: application.reviewed_at ? formatDateTime(application.reviewed_at) : null },
                { label: "Reviewed by", value: application.reviewed_by_name },
                { label: "Reason given", value: application.rejection_reason }
              ]}
            />
          </Card>

          <Card title="Who decides this" subtitle="Head office sees the queue; merchants decide">
            <p className="text-small text-muted">
              Approving, rejecting and asking for a correction stay with the merchant that holds this customer
              relationship, so this page is read-only. Open the merchant to see the team working the queue.
            </p>
            {pick(customer, "merchant_id") ? (
              <div style={{ marginTop: "var(--space-4)" }}>
                <ButtonLink
                  to={`/admin/merchants/${pick(customer, "merchant_id")}`}
                  variant="secondary"
                  icon="store"
                >
                  Open merchant
                </ButtonLink>
              </div>
            ) : null}
          </Card>

          <Card title="Timeline" subtitle="What happened, in order">
            <ol className="timeline list-plain">
              <li>
                <time dateTime={application.submitted_at}>{formatDate(application.submitted_at)}</time>
                Application submitted
              </li>
              {application.reviewed_at ? (
                <li>
                  <time dateTime={application.reviewed_at}>{formatDate(application.reviewed_at)}</time>
                  {application.status} by {application.reviewed_by_name ?? "a reviewer"}
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
    </div>
  );
}
