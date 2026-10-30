import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { listOtpLogs, type OtpLog } from "../../api/otp-logs.api";
import { queryKeys } from "../../api/query-keys";
import { Badge } from "../../components/common/StatusBadge";
import { Drawer, DrawerSection } from "../../components/feedback/Dialogs";
import { EmptyState, InlineError, RefreshIndicator } from "../../components/feedback/Feedback";
import { Field, SearchInput, Select } from "../../components/forms/Field";
import { Card, DetailsPanel, PageHeader, StatCard } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, TableHeader, type Column } from "../../components/tables/DataTable";
import { useSearchFilter, useUrlFilters } from "../../hooks/useUrlFilters";
import { formatDateTime, formatNumber, formatRelativeTime, humanize } from "../../utils/format";
import { channelLabel, type Tone } from "../../utils/labels";

const PAGE_SIZE = 20;
const FILTERS = ["search", "channel", "delivery"] as const;

const CHANNEL_OPTIONS = [
  { value: "CUSTOMER", label: "Customer app" },
  { value: "MERCHANT", label: "Merchant panel" },
  { value: "DELIVERY", label: "Delivery app" },
  { value: "ADMIN", label: "Admin panel" }
];

const DELIVERY_OPTIONS = [
  { value: "SENT", label: "Sent" },
  { value: "DELIVERED", label: "Delivered" },
  { value: "FAILED", label: "Failed" },
  { value: "PENDING", label: "Pending" }
];

const DELIVERY_TONE: Record<string, Tone> = { SENT: "info", DELIVERED: "success", FAILED: "danger", PENDING: "warning", QUEUED: "warning", SKIPPED: "neutral" };
const STATUS_TONE: Record<string, Tone> = { VERIFIED: "success", PENDING: "warning", EXPIRED: "neutral", FAILED: "danger", BLOCKED: "danger" };

/** Verified/consumed wins; otherwise expired once past expiry; otherwise still waiting. */
function outcome(log: OtpLog) {
  if (log.consumed || log.status === "VERIFIED") return "VERIFIED";
  if (log.status && log.status !== "PENDING" && log.status !== "ACTIVE") return log.status;
  if (log.expiresAt && new Date(log.expiresAt).getTime() < Date.now()) return "EXPIRED";
  return "PENDING";
}

const tone = (map: Record<string, Tone>, value: string | null) => (value ? (map[value] ?? "neutral") : "neutral");

export function OtpLogsPage() {
  const { values, page, setFilter, setPage, reset, hasFilters } = useUrlFilters(FILTERS);
  const [searchText, setSearchText] = useSearchFilter(values.search, (value) => setFilter("search", value));
  const [detail, setDetail] = useState<OtpLog | null>(null);

  const params = {
    search: values.search || undefined,
    login_channel: values.channel || undefined,
    delivery_status: values.delivery || undefined,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE
  };
  const query = useQuery({
    queryKey: queryKeys.otpLogs.list(params),
    queryFn: ({ signal }) => listOtpLogs(params, signal),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000
  });

  const rows = query.data?.items ?? [];
  // Counts on the cards describe the page shown, since the API returns no totals by outcome.
  const verified = rows.filter((r) => outcome(r) === "VERIFIED").length;
  const failedDelivery = rows.filter((r) => r.deliveryStatus === "FAILED").length;
  const pending = rows.filter((r) => outcome(r) === "PENDING").length;
  // Without a total, allow paging on while full pages keep coming.
  const total = query.data?.total ?? (rows.length === PAGE_SIZE ? page * PAGE_SIZE + 1 : (page - 1) * PAGE_SIZE + rows.length);

  const columns: Column<OtpLog>[] = [
    {
      key: "mobile",
      header: "Mobile",
      primary: true,
      sortValue: (l) => l.mobile ?? "",
      render: (l) => (
        <div className="cell-stack">
          <span className="mono nowrap cell-primary__title">{l.mobile ?? "—"}</span>
          {l.requestId ? (
            <small className="mono nowrap" title={l.requestId}>
              {l.requestId.slice(0, 8)}…
            </small>
          ) : null}
        </div>
      )
    },
    {
      key: "channel",
      header: "Channel",
      sortValue: (l) => l.channel ?? "",
      render: (l) => (l.channel ? <Badge tone="info">{channelLabel(l.channel)}</Badge> : <span className="cell-muted">—</span>)
    },
    {
      key: "delivery",
      header: "SMS",
      sortValue: (l) => l.deliveryStatus ?? "",
      render: (l) => (
        <div className="cell-stack">
          {l.deliveryStatus ? <Badge tone={tone(DELIVERY_TONE, l.deliveryStatus)}>{humanize(l.deliveryStatus)}</Badge> : <span className="cell-muted">—</span>}
          {l.provider ? <small className="nowrap">{l.provider}</small> : null}
        </div>
      )
    },
    {
      key: "outcome",
      header: "Status",
      sortValue: outcome,
      render: (l) => <Badge tone={tone(STATUS_TONE, outcome(l))}>{humanize(outcome(l))}</Badge>
    },
    {
      key: "attempts",
      header: "Attempts",
      align: "right",
      sortValue: (l) => l.attempts ?? -1,
      render: (l) =>
        l.attempts === null ? "—" : (
          <span className="nowrap" style={l.maxAttempts && l.attempts >= l.maxAttempts ? { color: "var(--red-600, #dc2626)", fontWeight: 600 } : undefined}>
            {formatNumber(l.attempts)}
            {l.maxAttempts ? <span className="text-muted"> / {formatNumber(l.maxAttempts)}</span> : null}
          </span>
        )
    },
    {
      key: "otp",
      header: "Code",
      render: (l) => (l.otp ? <strong className="mono">{l.otp}</strong> : <span className="cell-muted">—</span>)
    },
    {
      key: "requested",
      header: "Requested",
      sortValue: (l) => l.createdAt ?? "",
      render: (l) => (
        <div className="cell-stack">
          <span className="nowrap">{l.createdAt ? formatRelativeTime(l.createdAt) : "—"}</span>
          {l.createdAt ? <small className="nowrap">{formatDateTime(l.createdAt)}</small> : null}
        </div>
      )
    },
    {
      key: "expires",
      header: "Expires",
      sortValue: (l) => l.expiresAt ?? "",
      render: (l) => <span className="nowrap">{l.expiresAt ? formatDateTime(l.expiresAt) : "—"}</span>
    }
  ];

  return (
    <div className="page otp-logs-page">
      <PageHeader
        title="OTP Logs"
        documentTitle="OTP Logs"
        description="Every sign-in code requested across the apps: who asked, whether the SMS went out, and whether it was used. A code is shown only while it is still usable."
        meta={<RefreshIndicator active={query.isFetching && !query.isLoading} />}
      />

      <div className="kpi-grid" aria-label="OTP summary for this page">
        <StatCard label="On this page" icon="key" tone="blue" value={query.data ? formatNumber(rows.length) : "—"} hint={query.data?.total != null ? `${formatNumber(query.data.total)} in total` : "Latest first"} />
        <StatCard label="Verified" icon="checkCircle" tone="green" value={query.data ? formatNumber(verified) : "—"} hint="Code was used to sign in" />
        <StatCard label="Waiting" icon="clock" tone="amber" value={query.data ? formatNumber(pending) : "—"} hint="Not used and not expired" />
        <StatCard label="SMS failed" icon="alert" tone="red" value={query.data ? formatNumber(failedDelivery) : "—"} hint="Provider could not deliver" />
      </div>

      <Card bodyless className="table-card">
        <div className="status-tabs status-tabs--card" role="tablist" aria-label="Channel">
          {[{ value: "", label: "All channels" }, ...CHANNEL_OPTIONS].map((tab) => (
            <button key={tab.label} type="button" role="tab" aria-selected={values.channel === tab.value} onClick={() => setFilter("channel", tab.value)}>
              {tab.label}
            </button>
          ))}
        </div>
        <TableHeader title="OTP requests" count={query.data?.total ?? undefined} description="Newest first. Refreshes every 30 seconds. Select a row for details." />
        <FilterBar onReset={reset} canReset={hasFilters}>
          <SearchInput label="Search OTP logs" placeholder="Mobile number" value={searchText} onChange={(e) => setSearchText(e.target.value)} inputMode="numeric" />
          <Field label="SMS status" hideLabel>
            <Select value={values.delivery} onChange={(e) => setFilter("delivery", e.target.value)} placeholder="Any SMS status" options={DELIVERY_OPTIONS} />
          </Field>
        </FilterBar>

        {query.error && query.data ? (
          <div style={{ padding: "var(--space-4)" }}>
            <InlineError error={query.error} title="The list could not be refreshed" onRetry={() => void query.refetch()} />
          </div>
        ) : null}

        <DataTable
          caption="OTP logs"
          columns={columns}
          rows={query.data ? rows : undefined}
          getRowKey={(l) => l.id}
          onRowClick={setDetail}
          rowLabel={(l) => l.mobile ?? l.id}
          isLoading={query.isLoading}
          error={query.data ? undefined : query.error}
          onRetry={() => void query.refetch()}
          empty={
            hasFilters ? (
              <EmptyState icon="search" title="No OTP requests match" description="Try another number, channel or SMS status." />
            ) : (
              <EmptyState icon="key" title="No OTP requests yet" description="Sign-in codes appear here as soon as someone asks for one." />
            )
          }
        />
        {query.data && (page > 1 || total > PAGE_SIZE) ? (
          <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} itemLabel="requests" disabled={query.isFetching} />
        ) : null}
      </Card>

      <Drawer open={detail !== null} title={detail?.mobile ?? "OTP request"} subtitle={detail?.createdAt ? formatDateTime(detail.createdAt) : undefined} onClose={() => setDetail(null)}>
        {detail ? (
          <>
            <DrawerSection title="Request">
              <DetailsPanel
                items={[
                  { label: "Request ID", value: <span className="mono">{detail.requestId ?? "—"}</span> },
                  { label: "Mobile", value: <span className="mono">{detail.mobile ?? "—"}</span> },
                  { label: "Channel", value: detail.channel ? channelLabel(detail.channel) : "—" },
                  { label: "Purpose", value: detail.purpose ? humanize(detail.purpose) : "—" },
                  { label: "State", value: <Badge tone={tone(STATUS_TONE, outcome(detail))}>{humanize(outcome(detail))}</Badge> },
                  { label: "Code", value: detail.otp ? <strong className="mono">{detail.otp}</strong> : "Hidden once used or expired" },
                  { label: "Attempts", value: detail.attempts === null ? "—" : `${formatNumber(detail.attempts)}${detail.maxAttempts ? ` of ${formatNumber(detail.maxAttempts)}` : ""}` },
                  { label: "Requested", value: detail.createdAt ? formatDateTime(detail.createdAt) : "—" },
                  { label: "Expires", value: detail.expiresAt ? formatDateTime(detail.expiresAt) : "—" },
                  { label: "Used", value: detail.verifiedAt ? formatDateTime(detail.verifiedAt) : detail.consumed ? "Yes" : "No" }
                ]}
              />
            </DrawerSection>
            <DrawerSection title="SMS delivery">
              <DetailsPanel
                items={[
                  { label: "Status", value: detail.deliveryStatus ? <Badge tone={tone(DELIVERY_TONE, detail.deliveryStatus)}>{humanize(detail.deliveryStatus)}</Badge> : "—" },
                  { label: "Provider", value: detail.provider ?? "—" },
                  { label: "Provider message", value: detail.failureReason ?? "—" },
                  { label: "IP address", value: detail.ipAddress ? <span className="mono">{detail.ipAddress}</span> : "—" },
                  { label: "Device / app", value: detail.device ?? "—" }
                ]}
              />
            </DrawerSection>
            <DrawerSection title="Raw record">
              <pre className="mono text-small" style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
                {JSON.stringify(detail.raw, null, 2)}
              </pre>
            </DrawerSection>
          </>
        ) : null}
      </Drawer>
    </div>
  );
}

export default OtpLogsPage;
