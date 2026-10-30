import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { normalizeError } from "../../api/errors";
import { listMerchants } from "../../api/merchants.api";
import { listPricingChangeLogs, listPricingMonths, updatePriceEntry, type PriceEntry, type PricingChangeLog, type PricingMonth } from "../../api/pricing.api";
import { queryKeys } from "../../api/query-keys";
import { useOptionalAuth } from "../../auth/auth-context";
import { Button } from "../../components/common/Button";
import { Badge } from "../../components/common/StatusBadge";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert, EmptyState, InlineError, LoadingSkeleton, RefreshIndicator } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Input, Select, Textarea } from "../../components/forms/Field";
import { Card, PageHeader, StatCard } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, TableHeader, type Column } from "../../components/tables/DataTable";
import { useUrlFilters } from "../../hooks/useUrlFilters";
import { formatCurrency, formatDate, formatDateTime, formatNumber } from "../../utils/format";
import type { Tone } from "../../utils/labels";
import { cylinderLabel } from "../admin-reports/report-format";

const FILTERS = ["merchant", "month", "cylinder", "page"] as const;
const PAGE_SIZE = 20;

const MONTH_STATUS: Record<PricingMonth["status"], { label: string; tone: Tone }> = {
  ACTIVE: { label: "Active", tone: "success" },
  DRAFT: { label: "Draft", tone: "warning" },
  ARCHIVED: { label: "Archived", tone: "neutral" }
};

const money = (v: number | null | undefined) => (v === null || v === undefined ? "—" : formatCurrency(v));

function today() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
}

export function AdminPricingPage({
  merchantId: propMerchantId,
  isMerchantPanel = false,
  title = "Pricing"
}: {
  merchantId?: string;
  isMerchantPanel?: boolean;
  title?: string;
} = {}) {
  const auth = useOptionalAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { values, setFilter, setFilters } = useUrlFilters(FILTERS);

  const merchantParams = { limit: 100, offset: 0 };
  const merchants = useQuery({
    queryKey: queryKeys.merchants.list(merchantParams),
    queryFn: ({ signal }) => listMerchants(merchantParams, signal),
    staleTime: 5 * 60_000
  });

  const currentMerchantId = (auth?.user?.merchant as any)?.id || merchants.data?.items[0]?.id || (isMerchantPanel ? "merch-current" : undefined);
  const merchantId = propMerchantId || (isMerchantPanel ? currentMerchantId : undefined) || values.merchant;
  const [editing, setEditing] = useState<PriceEntry | null>(null);

  // Prices belong to a merchant, so open on the first one rather than an empty screen.
  useEffect(() => {
    const first = merchants.data?.items[0];
    if (!merchantId && first && !isMerchantPanel) setFilter("merchant", first.id);
  }, [merchantId, merchants.data, setFilter, isMerchantPanel]);

  const months = useQuery({
    queryKey: queryKeys.pricing.months(merchantId),
    queryFn: ({ signal }) => listPricingMonths(merchantId, signal),
    enabled: Boolean(merchantId)
  });

  // Newest month first from the API; default to the active one.
  const monthList = months.data ?? [];
  const month = monthList.find((m) => m.id === values.month) ?? monthList.find((m) => m.status === "ACTIVE") ?? monthList[0];
  const entries = [...(month?.entries ?? [])].sort((a, b) => (Number.parseFloat(cylinderLabel(a.cylinderType)) || 1e9) - (Number.parseFloat(cylinderLabel(b.cylinderType)) || 1e9));
  const editable = month ? month.status !== "ARCHIVED" : false;

  const page = Math.max(1, Number(values.page) || 1);
  const logParams = { merchantId, cylinderType: values.cylinder || undefined, page, pageSize: PAGE_SIZE };
  const logs = useQuery({
    queryKey: queryKeys.pricing.logs(logParams),
    queryFn: ({ signal }) => listPricingChangeLogs(logParams, signal),
    enabled: Boolean(merchantId),
    placeholderData: keepPreviousData
  });

  const entryColumns: Column<PriceEntry>[] = [
    { key: "type", header: "Cylinder", primary: true, render: (e) => <strong className="nowrap">{cylinderLabel(e.cylinderType)}</strong> },
    { key: "base", header: "BPCL base rate", align: "right", render: (e) => money(e.bpclBaseRate) },
    { key: "markup", header: "Tier markup", align: "right", render: (e) => money(e.tierMarkup) },
    { key: "price", header: "Customer price", align: "right", render: (e) => <strong>{money(e.customerPrice)}</strong> }
  ];

  const logColumns: Column<PricingChangeLog>[] = [
    {
      key: "when",
      header: "Changed",
      primary: true,
      render: (l) => (
        <div className="cell-stack">
          <span className="nowrap">{formatDateTime(l.changedAt)}</span>
          <small className="nowrap">Effective {formatDate(l.effectiveFrom)}</small>
        </div>
      )
    },
    { key: "type", header: "Cylinder", render: (l) => <span className="nowrap">{cylinderLabel(l.cylinderType)}</span> },
    {
      key: "base",
      header: "Base rate",
      align: "right",
      render: (l) => (
        <span className="nowrap">
          <span className="text-muted">{money(l.oldBpclBaseRate)}</span> → {money(l.newBpclBaseRate)}
        </span>
      )
    },
    {
      key: "markup",
      header: "Markup",
      align: "right",
      render: (l) => (
        <span className="nowrap">
          <span className="text-muted">{money(l.oldTierMarkup)}</span> → {money(l.newTierMarkup)}
        </span>
      )
    },
    {
      key: "price",
      header: "Customer price",
      align: "right",
      render: (l) => {
        const diff = l.oldCustomerPrice == null ? null : l.newCustomerPrice - l.oldCustomerPrice;
        return (
          <div className="cell-stack" style={{ alignItems: "flex-end" }}>
            <strong className="nowrap">{money(l.newCustomerPrice)}</strong>
            {diff ? <small className="nowrap" style={{ color: diff > 0 ? "var(--red-600, #dc2626)" : "var(--green-600, #16a34a)" }}>{diff > 0 ? "+" : "−"}{formatCurrency(Math.abs(diff))}</small> : null}
          </div>
        );
      }
    },
    {
      key: "by",
      header: "By",
      render: (l) => (
        <div className="cell-stack">
          <span className="nowrap">{l.changedBy?.name ?? "—"}</span>
          {l.reason ? <small title={l.reason} style={{ maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "block" }}>{l.reason}</small> : null}
        </div>
      )
    }
  ];

  const prices = entries.map((e) => e.customerPrice);

  return (
    <div className="page admin-pricing-page">
      <PageHeader
        title={title}
        documentTitle={title}
        description={isMerchantPanel ? "Monthly standard rates per cylinder, commercial tariffs, security deposits and pricing history." : "Monthly standard rates per cylinder, and every change made to them. Customer-specific prices are set on the customer's page."}
        meta={<RefreshIndicator active={(months.isFetching && !months.isLoading) || (logs.isFetching && !logs.isLoading)} />}
        actions={
          !isMerchantPanel ? (
            <Field label="Merchant" hideLabel>
              <Select
                value={merchantId}
                onChange={(event) => setFilters({ merchant: event.target.value, month: "", page: "" })}
                placeholder={merchants.isLoading ? "Loading merchants…" : "Select a merchant"}
                disabled={merchants.isLoading}
                options={(merchants.data?.items ?? []).map((m) => ({ value: m.id, label: m.business_name }))}
              />
            </Field>
          ) : undefined
        }
      />

      {merchants.error ? <InlineError error={merchants.error} title="Merchants could not be loaded" onRetry={() => void merchants.refetch()} /> : null}

      {!merchantId ? (
        merchants.isLoading ? (
          <LoadingSkeleton rows={4} label="Loading merchants" />
        ) : (
          <Card>
            <EmptyState icon="store" title="Choose a merchant" description="Prices are set per merchant. Pick one above." />
          </Card>
        )
      ) : (
        <>
          <div className="kpi-grid" aria-label="Pricing summary">
            <StatCard label="Month" icon="calendar" tone="blue" value={month?.label ?? "—"} hint={month ? `${formatDate(month.effectiveFrom)} – ${formatDate(month.effectiveTo)}` : "No pricing month yet"} />
            <StatCard label="GST" icon="fileText" tone="violet" value={month ? `${formatNumber(month.gstPercent)}%` : "—"} hint="Included in every price" />
            <StatCard label="Cheapest" icon="trendingDown" tone="green" value={prices.length ? formatCurrency(Math.min(...prices)) : "—"} hint="Lowest customer price this month" />
            <StatCard label="Last change" icon="history" tone="slate" value={month ? formatDate(month.updatedAt) : "—"} hint={month?.updatedBy ? `by ${month.updatedBy}` : undefined} />
          </div>

          <Card
            title="Standard rates"
            subtitle={month ? `${month.label} · customer price = base rate + markup, GST-inclusive` : undefined}
            actions={
              monthList.length ? (
                <span className="row" style={{ gap: 8 }}>
                  {month ? <Badge tone={MONTH_STATUS[month.status]?.tone ?? "neutral"}>{MONTH_STATUS[month.status]?.label ?? month.status}</Badge> : null}
                  <Field label="Pricing month" hideLabel>
                    <Select value={month?.id ?? ""} onChange={(e) => setFilter("month", e.target.value)} options={monthList.map((m) => ({ value: m.id, label: m.label }))} />
                  </Field>
                </span>
              ) : undefined
            }
            bodyless
          >
            {months.isLoading ? (
              <div style={{ padding: "var(--space-4)" }}>
                <LoadingSkeleton rows={5} label="Loading rates" />
              </div>
            ) : months.error ? (
              <div style={{ padding: "var(--space-4)" }}>
                <InlineError error={months.error} title="Rates could not be loaded" onRetry={() => void months.refetch()} />
              </div>
            ) : (
              <>
                {month && !editable ? (
                  <div style={{ padding: "var(--space-4) var(--space-4) 0" }}>
                    <Alert tone="info">This month is archived. Its rates are kept for history and cannot be changed.</Alert>
                  </div>
                ) : null}
                <DataTable
                  caption="Standard rates"
                  columns={entryColumns}
                  rows={entries}
                  getRowKey={(e) => `${e.cylinderType}-${e.tier}`}
                  onRowClick={editable ? (e) => setEditing(e) : undefined}
                  rowLabel={(e) => cylinderLabel(e.cylinderType)}
                  rowActions={editable ? (e) => [{ label: "Change price", icon: "edit", onSelect: () => setEditing(e) }] : undefined}
                  empty={<EmptyState icon="wallet" title="No rates in this month" description="Rates appear here once the month has entries." />}
                />
              </>
            )}
          </Card>

          <Card bodyless className="table-card">
            <TableHeader title="Change history" count={logs.data?.total} description="Every rate change, newest first, with who made it and why." />
            <FilterBar onReset={() => setFilters({ cylinder: "", page: "" })} canReset={Boolean(values.cylinder)}>
              <Field label="Cylinder" hideLabel>
                <Select
                  value={values.cylinder}
                  onChange={(e) => setFilters({ cylinder: e.target.value, page: "" })}
                  placeholder="All cylinders"
                  options={entries.map((e) => ({ value: e.cylinderType, label: cylinderLabel(e.cylinderType) }))}
                />
              </Field>
            </FilterBar>
            <DataTable
              caption="Price change history"
              columns={logColumns}
              rows={logs.data?.items}
              getRowKey={(l) => l.id}
              isLoading={logs.isLoading}
              error={logs.data ? undefined : logs.error}
              onRetry={() => void logs.refetch()}
              empty={<EmptyState icon="history" title="No price changes yet" description="Changes made to this merchant's rates are listed here." />}
            />
            {logs.data && logs.data.total > PAGE_SIZE ? (
              <Pagination page={page} pageSize={PAGE_SIZE} total={logs.data.total} onPageChange={(p) => setFilter("page", String(p))} itemLabel="changes" />
            ) : null}
          </Card>
        </>
      )}

      {merchantId && month ? (
        <PriceDialog
          merchantId={merchantId}
          month={month}
          entry={editing}
          onClose={() => setEditing(null)}
          onSaved={(entry) => {
            toast.success(`${cylinderLabel(entry.cylinderType)} price updated.`);
            void queryClient.invalidateQueries({ queryKey: queryKeys.pricing.all });
          }}
        />
      ) : null}
    </div>
  );
}

function PriceDialog({
  merchantId,
  month,
  entry,
  onClose,
  onSaved
}: {
  merchantId: string;
  month: PricingMonth;
  entry: PriceEntry | null;
  onClose: () => void;
  onSaved: (entry: PriceEntry) => void;
}) {
  const [form, setForm] = useState({ base: "", markup: "", effectiveFrom: "", reason: "" });
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (!entry) return;
    setSubmitted(false);
    const start = today() < month.effectiveFrom ? month.effectiveFrom : today() > month.effectiveTo ? month.effectiveTo : today();
    setForm({ base: String(entry.bpclBaseRate), markup: String(entry.tierMarkup), effectiveFrom: start, reason: "" });
  }, [entry, month]);

  const mutation = useMutation({
    mutationFn: () =>
      updatePriceEntry(merchantId, month.id, {
        cylinderType: entry!.cylinderType,
        tier: entry!.tier,
        bpclBaseRate: Number(form.base),
        tierMarkup: Number(form.markup),
        effectiveFrom: form.effectiveFrom || null,
        reason: form.reason.trim() || null
      }),
    onSuccess: () => {
      onSaved(entry!);
      onClose();
    }
  });

  const base = Number(form.base);
  const markup = Number(form.markup);
  const baseError = form.base === "" || !Number.isFinite(base) || base <= 0 ? "Enter the BPCL base rate." : undefined;
  const markupError = form.markup === "" || !Number.isFinite(markup) || markup < 0 ? "Enter the markup (0 or more)." : undefined;
  const dateError =
    form.effectiveFrom && (form.effectiveFrom < month.effectiveFrom || form.effectiveFrom > month.effectiveTo)
      ? `Must fall within ${month.label} (${formatDate(month.effectiveFrom)} – ${formatDate(month.effectiveTo)}).`
      : undefined;
  const changed = entry ? base !== entry.bpclBaseRate || markup !== entry.tierMarkup : false;
  const preview = !baseError && !markupError ? base + markup : null;
  const error = mutation.error ? normalizeError(mutation.error) : null;

  function submit() {
    setSubmitted(true);
    if (!baseError && !markupError && !dateError && changed) mutation.mutate();
  }

  return (
    <Modal
      open={entry !== null}
      title={entry ? `Change ${cylinderLabel(entry.cylinderType)} price` : "Change price"}
      description={`${month.label}. Takes effect for new orders from the date below; orders already placed keep their price.`}
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
          <Button icon="check" onClick={submit} disabled={!changed} loading={mutation.isPending} loadingText="Saving…">
            Save price
          </Button>
        </>
      }
    >
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <div className="form-grid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Field label="BPCL base rate (₹)" required error={submitted ? baseError : undefined}>
            <Input type="number" inputMode="decimal" min={0} step="0.01" value={form.base} onChange={(e) => setForm({ ...form, base: e.target.value })} autoFocus />
          </Field>
          <Field label="Tier markup (₹)" required error={submitted ? markupError : undefined}>
            <Input type="number" inputMode="decimal" min={0} step="0.01" value={form.markup} onChange={(e) => setForm({ ...form, markup: e.target.value })} />
          </Field>
        </div>
        <Alert tone="info">
          Customer price: <strong>{preview === null ? "—" : formatCurrency(preview)}</strong>
          {entry ? <span className="text-muted"> (now {formatCurrency(entry.customerPrice)})</span> : null}. The server computes the final figure.
        </Alert>
        <Field label="Effective from" optional error={dateError}>
          <Input type="date" min={month.effectiveFrom} max={month.effectiveTo} value={form.effectiveFrom} onChange={(e) => setForm({ ...form, effectiveFrom: e.target.value })} />
        </Field>
        <Field label="Reason" optional hint="Kept in the change history.">
          <Textarea rows={2} maxLength={500} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} placeholder="e.g. BPCL revised rate on 10 Oct" />
        </Field>
        {error ? <Alert tone="error">{(error.fieldErrors && Object.values(error.fieldErrors)[0]) || error.userMessage}</Alert> : null}
      </form>
    </Modal>
  );
}

export default AdminPricingPage;
