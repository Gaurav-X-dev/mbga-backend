import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { queryKeys } from "../../api/query-keys";
import {
  getLoginSessionStats,
  listLoginSessions,
  revokeLoginSession,
  type LoginSession
} from "../../api/sessions.api";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { Badge, StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { ConfirmDialog, DetailDrawer, DrawerSection } from "../../components/feedback/Dialogs";
import { EmptyState, InlineError, RefreshIndicator } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, SearchInput, Select } from "../../components/forms/Field";
import { Card, DetailsPanel, PageHeader, StatCard } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, TableHeader, type Column } from "../../components/tables/DataTable";
import { useSearchFilter, useUrlFilters } from "../../hooks/useUrlFilters";
import { formatDateTime, formatNumber, formatRelativeTime } from "../../utils/format";
import { channelLabel, roleLabel } from "../../utils/labels";
import { formatMobileNumber } from "../../utils/mobile";

const PAGE_SIZE = 20;
const FILTERS = ["search", "status", "channel"] as const;

const STATUS_OPTIONS = [
  { value: "ACTIVE", label: "Active" },
  { value: "EXPIRED", label: "Expired" },
  { value: "REVOKED", label: "Revoked" }
];

const CHANNEL_OPTIONS = [
  { value: "ADMIN", label: "Admin panel" },
  { value: "MERCHANT", label: "Merchant panel" },
  { value: "CUSTOMER", label: "Customer app" },
  { value: "DELIVERY", label: "Delivery app" }
];

function sessionName(session: LoginSession) {
  return session.user_name || formatMobileNumber(session.user_mobile) || "Unknown user";
}

function deviceLine(session: LoginSession) {
  return session.device_name || session.user_agent || "Unknown device";
}

export function LoginSessionsPage() {
  const auth = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const canRevoke = auth.can(PERMISSIONS.usersRevokeSessions);
  const { values, page, setFilter, setPage, reset, hasFilters } = useUrlFilters(FILTERS);
  const [searchText, setSearchText] = useSearchFilter(values.search, (value) => setFilter("search", value));
  const [detail, setDetail] = useState<LoginSession | null>(null);
  const [confirm, setConfirm] = useState<LoginSession | null>(null);

  const params = {
    search: values.search || undefined,
    status: values.status || undefined,
    login_channel: values.channel || undefined,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE
  };
  const query = useQuery({
    queryKey: queryKeys.loginSessions.list(params),
    queryFn: ({ signal }) => listLoginSessions(params, signal),
    placeholderData: keepPreviousData
  });
  const stats = useQuery({
    queryKey: queryKeys.loginSessions.stats(),
    queryFn: ({ signal }) => getLoginSessionStats(signal),
    staleTime: 30_000,
    retry: false
  });

  const revoke = useMutation({
    mutationFn: (session: LoginSession) => revokeLoginSession(session.id),
    onSuccess: (_updated, session) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.loginSessions.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.adminDashboard.all });
      setDetail(null);
      toast.success(`${sessionName(session)} has been signed out on ${deviceLine(session)}.`);
    }
  });

  const columns: Column<LoginSession>[] = [
    {
      key: "user",
      header: "User",
      primary: true,
      sortValue: sessionName,
      render: (session) => (
        <div className="cell-primary">
          <UserAvatar name={sessionName(session)} />
          <div className="cell-primary__text">
            <Link to={`/admin/users/${session.user_id}`} className="cell-primary__title">
              {sessionName(session)}
            </Link>
            <span className="cell-primary__subtitle">{roleLabel(session.user_role)}</span>
          </div>
        </div>
      )
    },
    {
      key: "channel",
      header: "Channel",
      sortValue: (session) => session.login_channel ?? "",
      render: (session) =>
        session.login_channel ? (
          <Badge tone="info">{channelLabel(session.login_channel)}</Badge>
        ) : (
          <span className="cell-muted">—</span>
        )
    },
    {
      key: "device",
      header: "Device",
      render: (session) => (
        <span className="row" style={{ flexWrap: "nowrap", gap: 8 }}>
          <Icon name={session.device_type === "mobile" ? "smartphone" : "monitor"} size={15} />
          <span className="cell-stack">
            <span>{deviceLine(session)}</span>
            {session.app_version ? <small>v{session.app_version}</small> : null}
          </span>
        </span>
      )
    },
    {
      key: "ip",
      header: "IP address",
      render: (session) =>
        session.ip_address ? <span className="mono">{session.ip_address}</span> : <span className="cell-muted">—</span>
    },
    {
      key: "started",
      header: "Started",
      sortValue: (session) => session.created_at ?? "",
      render: (session) => <span className="nowrap">{formatDateTime(session.created_at)}</span>
    },
    {
      key: "activity",
      header: "Last activity",
      sortValue: (session) => session.last_activity_at ?? "",
      render: (session) =>
        session.last_activity_at ? (
          <time dateTime={session.last_activity_at} title={formatDateTime(session.last_activity_at)} className="nowrap">
            {formatRelativeTime(session.last_activity_at)}
          </time>
        ) : (
          <span className="cell-muted">—</span>
        )
    },
    {
      key: "status",
      header: "Status",
      sortValue: (session) => session.status,
      render: (session) => <StatusBadge status={session.status} />
    }
  ];

  return (
    <div className="page sessions-page">
      <PageHeader
        title="Login Sessions"
        documentTitle="Login Sessions"
        description="Monitor signed-in sessions across admin, merchant, customer and delivery channels."
        meta={<RefreshIndicator active={query.isFetching && !query.isLoading} />}
        actions={
          <Button variant="secondary" icon="refresh" onClick={() => void query.refetch()} disabled={query.isFetching}>
            Refresh
          </Button>
        }
      />

      <div className="kpi-grid" aria-label="Session health">
        <StatCard label="Open Sessions" icon="devices" tone="blue" value={formatNumber(stats.data?.active)} hint="Signed in right now" />
        <StatCard label="Expired Sessions" icon="clock" tone="slate" value={formatNumber(stats.data?.expired)} hint="Ran past their lifetime" />
        <StatCard label="Revoked Sessions" icon="ban" tone="red" value={formatNumber(stats.data?.revoked)} hint="Ended by a person" />
        <StatCard
          label="Ended in last 24h"
          icon="history"
          tone="amber"
          value={formatNumber(stats.data?.ended_last_24h)}
          hint="Expired or revoked"
        />
      </div>

      {revoke.error ? <InlineError error={revoke.error} title="The session could not be revoked" /> : null}

      <Card bodyless className="table-card">
        <TableHeader
          title="Sessions"
          count={query.data?.total}
          description="Most recent activity first. Select a session for the full record."
        />
        <FilterBar onReset={reset} canReset={hasFilters}>
          <SearchInput
            label="Search sessions"
            placeholder="Search by user, device or IP address"
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
          />
          <Field label="Channel" hideLabel>
            <Select
              value={values.channel}
              onChange={(event) => setFilter("channel", event.target.value)}
              placeholder="All channels"
              options={CHANNEL_OPTIONS}
            />
          </Field>
          <Field label="Status" hideLabel>
            <Select
              value={values.status}
              onChange={(event) => setFilter("status", event.target.value)}
              placeholder="All statuses"
              options={STATUS_OPTIONS}
            />
          </Field>
        </FilterBar>

        {query.error && query.data ? (
          <div style={{ padding: "var(--space-4)" }}>
            <InlineError error={query.error} title="The list could not be refreshed" onRetry={() => void query.refetch()} />
          </div>
        ) : null}

        <DataTable
          caption="Login sessions"
          columns={columns}
          rows={query.data?.items}
          getRowKey={(session) => session.id}
          onRowClick={setDetail}
          isSelected={(session) => session.id === detail?.id}
          rowLabel={(session) => `${sessionName(session)} on ${deviceLine(session)}`}
          rowActions={(session) => [
            { label: "View details", icon: "eye", onSelect: () => setDetail(session) },
            {
              label: "Revoke session",
              icon: "ban",
              danger: true,
              hidden: session.status !== "ACTIVE" || !canRevoke,
              onSelect: () => setConfirm(session)
            }
          ]}
          isLoading={query.isLoading}
          error={query.error}
          onRetry={() => void query.refetch()}
          empty={
            hasFilters ? (
              <EmptyState
                icon="search"
                title="No sessions match your filters"
                description="Try a different search, channel or status."
                action={
                  <Button variant="secondary" onClick={reset}>
                    Clear filters
                  </Button>
                }
              />
            ) : (
              <EmptyState
                icon="devices"
                title="No sessions yet"
                description="Sessions appear here as people sign in to the panels and the apps."
              />
            )
          }
          footer={
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={query.data?.total ?? 0}
              onPageChange={setPage}
              itemLabel="sessions"
              disabled={query.isFetching}
            />
          }
        />
      </Card>

      {detail ? (
        <DetailDrawer
          open
          onClose={() => setDetail(null)}
          title={sessionName(detail)}
          subtitle={`${roleLabel(detail.user_role)} · ${channelLabel(detail.login_channel)}`}
          meta={<StatusBadge status={detail.status} />}
          footer={
            detail.status === "ACTIVE" && canRevoke ? (
              <>
                <Button variant="secondary" onClick={() => setDetail(null)}>
                  Close
                </Button>
                <Button variant="danger" icon="ban" onClick={() => setConfirm(detail)}>
                  Revoke session
                </Button>
              </>
            ) : (
              <Button variant="secondary" onClick={() => setDetail(null)}>
                Close
              </Button>
            )
          }
        >
          <DrawerSection title="Session">
            <DetailsPanel
              items={[
                { label: "Session reference", value: <span className="mono">{detail.id}</span> },
                { label: "Channel", value: channelLabel(detail.login_channel) },
                { label: "Started", value: formatDateTime(detail.created_at) },
                {
                  label: "Last activity",
                  value: detail.last_activity_at
                    ? `${formatDateTime(detail.last_activity_at)} (${formatRelativeTime(detail.last_activity_at)})`
                    : null
                },
                { label: "Expires", value: formatDateTime(detail.expires_at) },
                { label: "Revoked", value: detail.revoked_at ? formatDateTime(detail.revoked_at) : null },
                { label: "Revoked reason", value: detail.revoked_reason }
              ]}
            />
          </DrawerSection>
          <DrawerSection title="Device & network">
            <DetailsPanel
              items={[
                { label: "Device", value: deviceLine(detail) },
                { label: "Device type", value: detail.device_type },
                { label: "App version", value: detail.app_version },
                { label: "IP address", value: detail.ip_address ? <span className="mono">{detail.ip_address}</span> : null }
              ]}
            />
          </DrawerSection>
          <DrawerSection title="Account">
            <DetailsPanel
              items={[
                { label: "Name", value: detail.user_name },
                { label: "Mobile", value: formatMobileNumber(detail.user_mobile) },
                { label: "Role", value: roleLabel(detail.user_role) }
              ]}
            />
            <Link to={`/admin/users/${detail.user_id}`} className="btn btn--secondary" onClick={() => setDetail(null)}>
              Open user record
            </Link>
          </DrawerSection>
        </DetailDrawer>
      ) : null}

      <ConfirmDialog
        open={confirm !== null}
        title="Revoke this session?"
        description={
          confirm
            ? `${sessionName(confirm)} will be signed out on ${deviceLine(confirm)} and will need a new verification code to sign in again.`
            : ""
        }
        confirmLabel="Revoke session"
        onClose={() => setConfirm(null)}
        onConfirm={async () => {
          if (confirm) await revoke.mutateAsync(confirm);
        }}
      />
    </div>
  );
}
