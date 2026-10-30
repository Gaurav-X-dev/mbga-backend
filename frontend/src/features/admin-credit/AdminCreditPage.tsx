import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { getCreditReport, getCreditSettings, type CustomerCredit } from "../../api/credit.api";
import { listMerchants } from "../../api/merchants.api";
import { queryKeys } from "../../api/query-keys";
import { useOptionalAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { Badge, UserAvatar } from "../../components/common/StatusBadge";
import { EmptyState, InlineError, RefreshIndicator } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Checkbox, Field, SearchInput, Select } from "../../components/forms/Field";
import { Card, PageHeader, StatCard } from "../../components/layout/Page";
import { DataTable, FilterBar, TableHeader, type Column } from "../../components/tables/DataTable";
import { useUrlFilters } from "../../hooks/useUrlFilters";
import { formatCurrency, formatNumber } from "../../utils/format";
import { ConfigureCreditDialog, CreditHistoryDrawer, OverrideDialog } from "./CreditDialogs";
import { CreditSettingsCard } from "./CreditSettingsCard";

const PAGE_SIZE = 50;
const FILTERS = ["merchant", "exceeded", "search"] as const;

function UsageBar({ used, limit, exceeded }: { used: number; limit: number; exceeded: boolean }) {
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : used > 0 ? 100 : 0;
  // Exactly at the limit is allowed (rule 3), so red is kept for "over".
  const color = exceeded || used > limit ? "var(--red-500, #ef4444)" : pct >= 80 ? "var(--amber-500, #f59e0b)" : "var(--green-500, #16a34a)";
  return (
    <span className="row nowrap" style={{ gap: 8, flexWrap: "nowrap" }} aria-label={`${Math.round(pct)}% of limit used`}>
      <span style={{ display: "block", width: 90, height: 6, borderRadius: 999, background: "var(--border)" }}>
        <span style={{ display: "block", height: "100%", width: `${pct}%`, borderRadius: 999, background: color }} />
      </span>
      <small className="text-muted">{Math.round(pct)}%</small>
    </span>
  );
}

/** Credit on with a ₹0 limit is never checked by the backend, so it is not "on credit". */
function isChecked(c: CustomerCredit) {
  return c.creditEnabled && c.creditLimit > 0;
}

export interface AdminCreditPageProps {
  merchantId?: string;
  isMerchantPanel?: boolean;
  title?: string;
}

export function AdminCreditPage({ merchantId: propMerchantId, isMerchantPanel = false, title = "Credit control" }: AdminCreditPageProps = {}) {
  const auth = useOptionalAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const canManage = auth?.can(PERMISSIONS.creditManage) ?? true;
  const canOverride = auth?.can(PERMISSIONS.creditOverride) ?? true;
  const { values, setFilter, clearFilters } = useUrlFilters(FILTERS);
  const [offset, setOffset] = useState(0);
  const [configuring, setConfiguring] = useState<CustomerCredit | null>(null);
  const [overriding, setOverriding] = useState<CustomerCredit | null>(null);
  const [history, setHistory] = useState<CustomerCredit | null>(null);

  const settings = useQuery({ queryKey: queryKeys.credit.settings(), queryFn: ({ signal }) => getCreditSettings(signal) });
  // Rule 1: nothing is blocked while the global switch is off, whatever a customer's figures say.
  const enforced = settings.data?.creditLimitEnabled === true;

  const currentMerchantId =
    propMerchantId ||
    (isMerchantPanel ? (auth?.user?.merchant as any)?.id || "merch-current" : undefined) ||
    values.merchant;

  const merchantParams = { limit: 100, offset: 0 };
  const merchants = useQuery({
    queryKey: queryKeys.merchants.list(merchantParams),
    queryFn: ({ signal }) => listMerchants(merchantParams, signal),
    enabled: !isMerchantPanel && (auth ? auth.can(PERMISSIONS.merchantsView) : true),
    staleTime: 5 * 60_000,
    retry: false
  });
  const merchantName = useMemo(
    () => new Map((merchants.data?.items ?? []).map((m) => [m.id, m.business_name])),
    [merchants.data]
  );

  const params = { merchantId: currentMerchantId || undefined, exceededOnly: values.exceeded === "1", limit: PAGE_SIZE, offset };
  const report = useQuery({
    queryKey: queryKeys.credit.report(params),
    queryFn: ({ signal }) => getCreditReport(params, signal),
    placeholderData: keepPreviousData
  });

  // The report has no search parameter; filter the loaded page by name or customer ID.
  const rows = useMemo(() => {
    const items = report.data?.items ?? [];
    const q = values.search.trim().toLowerCase();
    return q ? items.filter((c) => [c.customerName, c.customerCode, c.customerId].some((v) => v?.toLowerCase().includes(q))) : items;
  }, [report.data, values.search]);

  const items = report.data?.items ?? [];
  // Rule 1: a customer is only checked with credit on AND a limit above zero.
  const onCredit = items.filter(isChecked);
  const totals = {
    limit: onCredit.reduce((s, c) => s + c.creditLimit, 0),
    used: onCredit.reduce((s, c) => s + c.usedCredit, 0),
    exceeded: items.filter((c) => c.exceeded).length,
    nearLimit: onCredit.filter((c) => !c.exceeded && c.creditLimit > 0 && c.usedCredit / c.creditLimit >= 0.8).length
  };
  const hasMore = (report.data?.items.length ?? 0) >= PAGE_SIZE;

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.credit.all });
  }

  const columns: Column<CustomerCredit>[] = [
    {
      key: "customer",
      header: "Customer",
      primary: true,
      sortValue: (c) => c.customerName,
      render: (c) => (
        <div className="cell-primary">
          <UserAvatar name={c.customerName} />
          <div className="cell-primary__text">
            <Link
              to={isMerchantPanel ? `/merchant/customers/${encodeURIComponent(c.customerId)}` : `/admin/customer-accounts/${encodeURIComponent(c.customerId)}?merchant=${encodeURIComponent(c.merchantId)}`}
              className="cell-primary__title"
              style={{ display: "block", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
              title={c.customerName}
            >
              {c.customerName}
            </Link>
            <span className="cell-primary__subtitle nowrap">{merchantName.get(c.merchantId) ?? "Merchant"}</span>
          </div>
        </div>
      )
    },
    {
      key: "customerId",
      header: "Customer ID",
      sortValue: (c) => c.customerCode ?? c.customerId,
      render: (c) => (
        <button
          type="button"
          className="btn--link mono nowrap text-small"
          title={`${c.customerId} · click to copy`}
          onClick={(event) => {
            event.stopPropagation();
            void navigator.clipboard
              ?.writeText(c.customerCode ?? c.customerId)
              .then(() => toast.success("Customer ID copied."))
              .catch(() => undefined);
          }}
        >
          {c.customerCode ?? `${c.customerId.slice(0, 8)}…`}
        </button>
      )
    },
    {
      key: "limit",
      header: "Limit",
      align: "right",
      sortValue: (c) => (c.creditEnabled ? c.creditLimit : -1),
      render: (c) =>
        isChecked(c) ? (
          <div className="cell-stack" style={{ alignItems: "flex-end" }}>
            <strong className="nowrap">{formatCurrency(c.creditLimit)}</strong>
            <small className="nowrap">{c.creditDays ? `${c.creditDays} days to pay` : "No terms set"}</small>
          </div>
        ) : (
          <span className="text-muted" title={c.creditEnabled ? "Credit is on but the limit is ₹0, so orders are not checked." : undefined}>
            {c.creditEnabled ? "₹0 · not checked" : "No credit"}
          </span>
        )
    },
    {
      key: "used",
      header: "Used",
      align: "right",
      sortValue: (c) => c.usedCredit,
      render: (c) => <span className="nowrap">{formatCurrency(c.usedCredit)}</span>
    },
    {
      key: "available",
      header: "Available",
      align: "right",
      sortValue: (c) => c.availableCredit,
      render: (c) => (
        <strong className="nowrap" style={{ color: c.availableCredit < 0 && isChecked(c) ? "var(--red-600, #dc2626)" : undefined }}>
          {isChecked(c) ? formatCurrency(c.availableCredit) : "—"}
        </strong>
      )
    },
    {
      key: "usage",
      header: "Usage",
      hideOnMobile: true,
      sortValue: (c) => (c.creditLimit > 0 ? c.usedCredit / c.creditLimit : 0),
      render: (c) => (isChecked(c) ? <UsageBar used={c.usedCredit} limit={c.creditLimit} exceeded={c.exceeded} /> : null)
    },
    {
      key: "status",
      header: "Status",
      sortValue: (c) => (isChecked(c) ? (c.exceeded ? 0 : 1) : 2),
      render: (c) =>
        !isChecked(c) ? (
          <Badge tone="neutral">{c.creditEnabled ? "No limit set" : "Off"}</Badge>
        ) : c.exceeded ? (
          <Badge tone={enforced ? "danger" : "warning"}>{enforced ? "Over limit" : "Over limit · not enforced"}</Badge>
        ) : (
          <Badge tone="success">Within limit</Badge>
        )
    }
  ];

  return (
    <div className="page admin-credit-page">
      <PageHeader
        title={title}
        documentTitle={title}
        description="Who can order on credit, how much, and who is over their limit."
        meta={<RefreshIndicator active={report.isFetching && !report.isLoading} />}
        actions={
          <Button variant="secondary" icon="refresh" onClick={refresh} disabled={report.isFetching}>
            Refresh
          </Button>
        }
      />

      <div className="kpi-grid" aria-label="Credit summary">
        <StatCard label="Customers on credit" icon="users" tone="blue" value={report.data ? formatNumber(onCredit.length) : "—"} hint="Credit on with a limit above ₹0" />
        <StatCard
          label="Credit in use"
          icon="wallet"
          tone="violet"
          value={report.data ? formatCurrency(totals.used) : "—"}
          hint={report.data ? `of ${formatCurrency(totals.limit)} extended` : "Owed against limits"}
        />
        <StatCard
          label="Near limit"
          icon="warning"
          tone={totals.nearLimit ? "amber" : "slate"}
          value={report.data ? formatNumber(totals.nearLimit) : "—"}
          hint="80% or more used"
        />
        <StatCard
          label="Over limit"
          icon="ban"
          tone={totals.exceeded ? "red" : "slate"}
          value={report.data ? formatNumber(totals.exceeded) : "—"}
          hint={settings.data ? (enforced ? "Customer & driver orders blocked" : "Not enforced — global switch is off") : "Over their limit"}
        />
      </div>

      <CreditSettingsCard canManage={canManage} />

      <p className="meta">
        Checked when a customer places, repeats or reorders, and when a driver increases an order at the door. Orders created
        manually by merchant or admin staff are never blocked. An order exactly at the limit is allowed; only going over is
        refused. Used credit = unpaid invoice balances + active orders not yet invoiced, and payments free it up automatically.
      </p>

      <Card bodyless className="table-card">
        <TableHeader title="Customer credit" count={rows.length} description="Select a customer to change their limit, approve an override or see their history." />
        <FilterBar
          onReset={() => {
            setOffset(0);
            clearFilters(["merchant", "exceeded", "search"]);
          }}
          canReset={Boolean(values.merchant || values.exceeded || values.search)}
        >
          <SearchInput label="Search customers" placeholder="Customer name or ID" value={values.search} onChange={(e) => setFilter("search", e.target.value)} />
          {!isMerchantPanel && (auth ? auth.can(PERMISSIONS.merchantsView) : true) ? (
            <Field label="Merchant" hideLabel>
              <Select
                value={values.merchant}
                onChange={(e) => {
                  setOffset(0);
                  setFilter("merchant", e.target.value);
                }}
                placeholder="All merchants"
                options={(merchants.data?.items ?? []).map((m) => ({ value: m.id, label: m.business_name }))}
              />
            </Field>
          ) : null}
          <Checkbox
            label="Over limit only"
            checked={values.exceeded === "1"}
            onChange={(e) => {
              setOffset(0);
              setFilter("exceeded", e.target.checked ? "1" : "");
            }}
          />
        </FilterBar>

        {report.error && report.data ? (
          <div style={{ padding: "var(--space-4)" }}>
            <InlineError error={report.error} title="The list could not be refreshed" onRetry={() => void report.refetch()} />
          </div>
        ) : null}

        <DataTable
          caption="Customer credit"
          columns={columns}
          rows={report.data ? rows : undefined}
          getRowKey={(c) => c.customerId}
          onRowClick={(c) => (canManage ? setConfiguring(c) : setHistory(c))}
          rowLabel={(c) => c.customerName}
          rowActions={(c) => [
            { label: "Change limit", icon: "edit", hidden: !canManage, onSelect: () => setConfiguring(c) },
            { label: "Approve temporary override", icon: "unlock", hidden: !canOverride || !isChecked(c), onSelect: () => setOverriding(c) },
            { label: "View history", icon: "history", onSelect: () => setHistory(c) }
          ]}
          isLoading={report.isLoading}
          error={report.data ? undefined : report.error}
          onRetry={() => void report.refetch()}
          empty={
            values.exceeded || values.search || values.merchant ? (
              <EmptyState icon="search" title="No customers match" description={values.exceeded ? "Nobody is over their limit." : "Try another merchant or name."} />
            ) : (
              <EmptyState icon="wallet" title="No customer credit yet" description="Customers appear here once credit is set up for them." />
            )
          }
          footer={
            offset > 0 || hasMore ? (
              <div className="row-between" style={{ padding: "var(--space-3) var(--space-4)" }}>
                <span className="text-muted text-small">
                  Showing {formatNumber(offset + 1)}–{formatNumber(offset + (report.data?.items.length ?? 0))}
                </span>
                <span className="row" style={{ gap: 8 }}>
                  <Button variant="secondary" size="sm" disabled={offset === 0 || report.isFetching} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                    Previous
                  </Button>
                  <Button variant="secondary" size="sm" disabled={!hasMore || report.isFetching} onClick={() => setOffset(offset + PAGE_SIZE)}>
                    Next
                  </Button>
                </span>
              </div>
            ) : undefined
          }
        />
      </Card>

      <ConfigureCreditDialog
        customer={configuring}
        onClose={() => setConfiguring(null)}
        onSaved={() => {
          toast.success(`Credit updated for ${configuring?.customerName ?? "the customer"}.`);
          refresh();
        }}
      />
      <OverrideDialog
        customer={overriding}
        onClose={() => setOverriding(null)}
        onApproved={(message) => {
          toast.success(message);
          refresh();
        }}
      />
      {history ? <CreditHistoryDrawer customer={history} onClose={() => setHistory(null)} /> : null}
    </div>
  );
}

export default AdminCreditPage;
