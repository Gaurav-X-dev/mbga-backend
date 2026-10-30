import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import {
  approveCustomer,
  getCustomer,
  getCustomerEligibility,
  getCustomerPaymentSummary,
  getCustomerPricing,
  rejectCustomer,
  removeCustomerPrice,
  setCustomerPrice,
  type CustomerPriceItem
} from "../../api/customers.api";
import { normalizeError } from "../../api/errors";
import type { Address } from "../../api/orders.api";
import { queryKeys } from "../../api/query-keys";
import { useAuth } from "../../auth/auth-context";
import { Button, ButtonLink, IconButton } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { Badge, StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { ConfirmationDialog, Modal } from "../../components/feedback/Dialogs";
import { Alert, EmptyState, ErrorState, InlineError, LoadingSkeleton } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Input, Textarea } from "../../components/forms/Field";
import { Card, DetailsPanel, MiniStat, PageHeader } from "../../components/layout/Page";
import { formatCurrency, formatDate, formatDateTime, formatRelativeTime, humanize, todayInputValue } from "../../utils/format";
import { CustomerOrdersCard } from "../customers/CustomerOrdersCard";
import { CustomerKycDocumentsCard } from "./CustomerKycDocumentsCard";
import { customerName } from "./customer-utils";

function formatAddress(address: Address | null | undefined) {
  if (!address) return null;
  return [address.line1, address.line2, address.city, address.state, address.pincode].filter(Boolean).join(", ") || null;
}

export function AdminCustomerDetailPage() {
  const { customerId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const auth = useAuth();
  const currentMerchantId = (auth.user?.merchant as any)?.id;
  const merchantId = searchParams.get("merchant") || currentMerchantId || "";
  const toast = useToast();
  const queryClient = useQueryClient();
  const [deciding, setDeciding] = useState<"approve" | "reject" | null>(null);
  const [reason, setReason] = useState("");
  const isMerchant = auth.channel === "merchant";
  const backHref = isMerchant
    ? "/merchant/customers"
    : merchantId
      ? `/admin/customer-accounts?merchant=${encodeURIComponent(merchantId)}`
      : "/admin/customer-accounts";

  const enabled = Boolean(merchantId && customerId);
  const query = useQuery({
    queryKey: queryKeys.customers.detail(merchantId, customerId),
    queryFn: ({ signal }) => getCustomer(merchantId, customerId, signal),
    enabled
  });
  const eligibility = useQuery({
    queryKey: queryKeys.customers.eligibility(merchantId, customerId),
    queryFn: ({ signal }) => getCustomerEligibility(merchantId, customerId, signal),
    enabled,
    retry: false
  });
  const payments = useQuery({
    queryKey: queryKeys.customers.payments(merchantId, customerId),
    queryFn: ({ signal }) => getCustomerPaymentSummary(merchantId, customerId, signal),
    enabled,
    retry: false
  });

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.customers.all });
    void queryClient.invalidateQueries({ queryKey: queryKeys.customerKyc.all });
  }

  if (!merchantId) {
    return (
      <div className="page">
        <Card>
          <EmptyState
            icon="store"
            title="Merchant not specified"
            description="Open the customer from the Customers list so the panel knows which merchant they belong to."
            action={<ButtonLink to="/admin/customer-accounts" variant="secondary">Back to customers</ButtonLink>}
          />
        </Card>
      </div>
    );
  }
  if (query.isLoading) return <LoadingSkeleton rows={8} label="Loading customer" />;
  if (query.error || !query.data) {
    return (
      <div className="page">
        <Card>
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        </Card>
      </div>
    );
  }

  const customer = query.data;
  const name = customerName(customer);
  const awaitingReview = [customer.kycStatus, customer.accountStatus].some((s) => /PENDING|REVIEW|SUBMITTED/i.test(s ?? ""));

  return (
    <div className="page admin-customer-detail-page">
      <PageHeader
        eyebrow={customer.code ? <span className="mono">{customer.code}</span> : "Customer"}
        title={name}
        documentTitle={name}
        meta={
          <span className="row" style={{ gap: 8 }}>
            <StatusBadge status={customer.accountStatus} />
            <Badge tone="neutral">KYC: {humanize(customer.kycStatus)}</Badge>
            {customer.customerType ? <Badge tone="info">{humanize(customer.customerType)}</Badge> : null}
            {customer.registeredAt ? <span className="meta">Registered {formatRelativeTime(customer.registeredAt)}</span> : null}
          </span>
        }
        actions={
          <>
            <ButtonLink to={backHref} variant="secondary" icon="arrowLeft">
              All customers
            </ButtonLink>
            {awaitingReview ? (
              <>
                <Button variant="danger" icon="xCircle" onClick={() => setDeciding("reject")}>
                  Reject
                </Button>
                <Button icon="checkCircle" onClick={() => setDeciding("approve")}>
                  Approve
                </Button>
              </>
            ) : null}
          </>
        }
      />

      {customer.rejectionReason ? (
        <Alert tone="error" title="Registration rejected">
          {customer.rejectionReason}
        </Alert>
      ) : null}

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 2fr) minmax(300px, 1fr)", gap: "var(--space-5)", alignItems: "start" }}>
        <div className="stack-lg">
          <Card title="Account">
            <div className="row" style={{ marginBottom: "var(--space-5)", flexWrap: "nowrap", gap: "var(--space-3)" }}>
              <UserAvatar name={name} size="lg" />
              <div className="cell-stack">
                <strong>{name}</strong>
                <small>{customer.ownerName && customer.businessName ? `Owner: ${customer.ownerName}` : customer.mobile}</small>
              </div>
            </div>
            <DetailsPanel
              items={[
                { label: "Mobile", value: customer.mobile },
                { label: "Email", value: customer.email },
                { label: "Customer type", value: customer.customerType ? humanize(customer.customerType) : null },
                { label: "Pricing tier", value: humanize(customer.pricingTier) },
                { label: "GSTIN", value: customer.gstin ? <span className="mono">{customer.gstin}</span> : null },
                { label: "Delivery address", value: formatAddress(customer.deliveryAddress) },
                { label: "Registered", value: customer.registeredAt ? formatDateTime(customer.registeredAt) : null },
                { label: "Approved", value: customer.approvedAt ? formatDateTime(customer.approvedAt) : null },
                { label: "Last order", value: customer.lastOrderAt ? `${formatDate(customer.lastOrderAt)} · ${formatRelativeTime(customer.lastOrderAt)}` : "Never" }
              ]}
            />
          </Card>

          <CustomerOrdersCard merchantId={merchantId} customerId={customerId} />

          <PricingCard merchantId={merchantId} customerId={customerId} />

          {customer.sites?.length ? (
            <Card title="Delivery sites" subtitle="Where this customer takes delivery">
              <ul className="doc-list list-plain">
                {customer.sites.map((site) => (
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
          <Card title="Balance" subtitle={payments.data?.lastPaymentAt ? `Last paid ${formatRelativeTime(payments.data.lastPaymentAt)}` : undefined}>
            {payments.isLoading ? (
              <LoadingSkeleton rows={2} label="Loading balance" />
            ) : payments.data ? (
              <div className="stack">
                <MiniStat label="Still owed" value={formatCurrency(payments.data.runningBalance)} icon="wallet" tone={payments.data.runningBalance > 0 ? "red" : "green"} />
                <MiniStat label="Overdue" value={formatCurrency(payments.data.overdueAmount)} icon="warning" tone={payments.data.overdueAmount > 0 ? "amber" : "slate"} />
                <DetailsPanel
                  columns={1}
                  items={[
                    { label: "Total invoiced", value: formatCurrency(payments.data.totalInvoiced) },
                    { label: "Total paid", value: formatCurrency(payments.data.totalPaid) }
                  ]}
                />
                <ButtonLink to={`/admin/payments?merchant=${encodeURIComponent(merchantId)}&search=${encodeURIComponent(name)}`} variant="secondary" size="sm" icon="wallet">
                  View payments
                </ButtonLink>
              </div>
            ) : (
              <DetailsPanel columns={1} items={[{ label: "Running balance", value: formatCurrency(customer.runningBalance) }]} />
            )}
          </Card>

          <Card title="Can order?">
            {eligibility.isLoading ? (
              <LoadingSkeleton rows={1} label="Checking" />
            ) : eligibility.error ? (
              <InlineError error={eligibility.error} onRetry={() => void eligibility.refetch()} />
            ) : eligibility.data?.eligible ? (
              <Alert tone="success">Orders can be placed for this customer.</Alert>
            ) : (
              <Alert tone="warning" title="Orders are blocked">
                {eligibility.data?.reasons?.length ? (
                  <ul style={{ margin: 0, paddingLeft: "1.2em" }}>
                    {eligibility.data.reasons.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                ) : (
                  "The customer is not eligible yet."
                )}
              </Alert>
            )}
          </Card>

          <CustomerKycDocumentsCard key={customer.id} merchantId={merchantId}
            applicationId={customer.applicationId} documents={customer.documents ?? []} />
        </div>
      </div>

      <ConfirmationDialog
        open={deciding === "approve"}
        title="Approve this customer?"
        description={`${name} will be able to place orders once approved.`}
        confirmLabel="Approve"
        confirmVariant="primary"
        onClose={() => setDeciding(null)}
        onConfirm={async () => {
          await approveCustomer(merchantId, customerId);
          toast.success(`${name} approved.`);
          invalidate();
        }}
      />
      <ConfirmationDialog
        open={deciding === "reject"}
        title="Reject this registration?"
        description="The customer is told why, and can correct and resubmit."
        confirmLabel="Reject"
        confirmDisabled={reason.trim().length < 3}
        onClose={() => {
          setDeciding(null);
          setReason("");
        }}
        onConfirm={async () => {
          await rejectCustomer(merchantId, customerId, reason.trim());
          toast.success(`${name} rejected.`);
          setReason("");
          invalidate();
        }}
      >
        <Field label="Reason" required hint="At least 3 characters. Shown to the customer.">
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} maxLength={500} autoFocus />
        </Field>
      </ConfirmationDialog>
    </div>
  );
}

function PricingCard({ merchantId, customerId }: { merchantId: string; customerId: string }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.customers.pricing(merchantId, customerId),
    queryFn: ({ signal }) => getCustomerPricing(merchantId, customerId, signal)
  });
  const [editing, setEditing] = useState<CustomerPriceItem | null>(null);
  const [removing, setRemoving] = useState<CustomerPriceItem | null>(null);

  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.customers.pricing(merchantId, customerId) });

  return (
    <Card title="Pricing" subtitle={query.data ? `${humanize(query.data.tier)} tier · GST-inclusive per cylinder` : "Per-cylinder price this customer pays"}>
      {query.isLoading ? (
        <LoadingSkeleton rows={4} label="Loading prices" />
      ) : query.error ? (
        <InlineError error={query.error} onRetry={() => void query.refetch()} />
      ) : !query.data?.items?.length ? (
        <p className="text-muted">No prices set for this merchant yet.</p>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Cylinder</th>
                <th style={{ textAlign: "right" }}>Tier price</th>
                <th style={{ textAlign: "right" }}>Customer pays</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {query.data.items.map((item) => (
                <tr key={item.cylinderType}>
                  <td>{item.cylinderLabel}</td>
                  <td style={{ textAlign: "right" }} className={item.override ? "text-muted" : undefined}>
                    {item.tierPrice === null ? "—" : formatCurrency(item.tierPrice)}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <div className="cell-stack" style={{ alignItems: "flex-end" }}>
                      <strong>{item.effectivePrice === null ? "—" : formatCurrency(item.effectivePrice)}</strong>
                      {item.override ? (
                        <small title={item.override.reason ?? undefined}>
                          Special price since {formatDate(item.override.effectiveFrom)}
                          {item.override.setBy?.trim() ? ` By ${item.override.setBy.trim()}` : ""}
                        </small>
                      ) : null}
                    </div>
                  </td>
                  <td>
                    <span className="row" style={{ gap: 4, flexWrap: "nowrap", justifyContent: "flex-end" }}>
                      <IconButton icon="edit" label={`Set price for ${item.cylinderLabel}`} onClick={() => setEditing(item)} />
                      {item.override ? <IconButton icon="trash" label={`Remove special price for ${item.cylinderLabel}`} onClick={() => setRemoving(item)} /> : null}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <PriceDialog
        item={editing}
        onClose={() => setEditing(null)}
        onSave={async (input) => {
          if (!editing) return;
          await setCustomerPrice(merchantId, customerId, editing.cylinderType, input);
          toast.success(`${editing.cylinderLabel} price set to ${formatCurrency(input.overridePrice)}.`);
          refresh();
        }}
      />
      <ConfirmationDialog
        open={removing !== null}
        title="Remove the special price?"
        description={removing ? `${removing.cylinderLabel} goes back to the ${formatCurrency(removing.tierPrice)} tier price on the next order.` : ""}
        confirmLabel="Remove"
        onClose={() => setRemoving(null)}
        onConfirm={async () => {
          if (!removing) return;
          await removeCustomerPrice(merchantId, customerId, removing.cylinderType);
          toast.success(`${removing.cylinderLabel} is back on the tier price.`);
          refresh();
        }}
      />
    </Card>
  );
}

function PriceDialog({
  item,
  onClose,
  onSave
}: {
  item: CustomerPriceItem | null;
  onClose: () => void;
  onSave: (input: { overridePrice: number; effectiveFrom?: string; reason?: string }) => Promise<void>;
}) {
  const [price, setPrice] = useState("");
  const [from, setFrom] = useState("");
  const [reason, setReason] = useState("");
  const [lastItem, setLastItem] = useState<CustomerPriceItem | null>(null);
  if (item !== lastItem) {
    setLastItem(item);
    setPrice(item?.override ? String(item.override.overridePrice) : item?.effectivePrice != null ? String(item.effectivePrice) : "");
    setFrom(todayInputValue());
    setReason("");
  }

  const mutation = useMutation({
    mutationFn: () => onSave({ overridePrice: Number(price), effectiveFrom: from || undefined, reason: reason.trim() || undefined }),
    onSuccess: onClose
  });
  const valid = Number(price) > 0;

  return (
    <Modal
      open={item !== null}
      title={item ? `Special price · ${item.cylinderLabel}` : "Special price"}
      description="Applies everywhere this customer is priced: quotes, orders and invoices."
      onClose={() => {
        mutation.reset();
        onClose();
      }}
      busy={mutation.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button icon="check" onClick={() => mutation.mutate()} disabled={!valid} loading={mutation.isPending} loadingText="Saving…">
            Save price
          </Button>
        </>
      }
    >
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) mutation.mutate();
        }}
      >
        {item?.tierPrice != null ? <p className="meta">Tier price is {formatCurrency(item.tierPrice)} (GST-inclusive).</p> : null}
        <div className="grid-2">
          <Field label="Price per cylinder (₹)" required>
            <Input type="number" min={1} step="0.01" value={price} onChange={(e) => setPrice(e.target.value)} autoFocus />
          </Field>
          <Field label="Effective from" optional>
            <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          </Field>
        </div>
        <Field label="Reason" optional>
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={500} placeholder="e.g. Annual contract rate" />
        </Field>
        {mutation.error ? <Alert tone="error">{normalizeError(mutation.error).userMessage}</Alert> : null}
      </form>
    </Modal>
  );
}

export default AdminCustomerDetailPage;
