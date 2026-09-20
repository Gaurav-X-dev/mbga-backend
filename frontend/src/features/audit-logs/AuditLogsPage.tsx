import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { getAuditLog, listAuditLogs, type AuditLog } from "../../api/audit-logs.api";
import { queryKeys } from "../../api/query-keys";
import { listUsers } from "../../api/users.api";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { Drawer } from "../../components/feedback/Dialogs";
import { EmptyState, ErrorState, InlineError, LoadingSkeleton, RefreshIndicator } from "../../components/feedback/Feedback";
import { Field, Input, Select } from "../../components/forms/Field";
import { Card, DetailsPanel, PageHeader } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, type Column } from "../../components/tables/DataTable";
import { useUrlFilters } from "../../hooks/useUrlFilters";
import { formatDateTime, formatRelativeTime, todayInputValue } from "../../utils/format";
import { AUDIT_ENTITY_OPTIONS, AUDIT_EVENT_OPTIONS, auditEntityLabel, auditEventLabel } from "../../utils/labels";
import { userDisplayName } from "../users/user-utils";

const PAGE_SIZE = 25;
const FILTERS = ["from", "to", "action", "area", "actor"] as const;

/** Local calendar day boundaries sent as UTC instants. */
function startOfDay(value: string) {
  return value ? new Date(`${value}T00:00:00`).toISOString() : undefined;
}
function endOfDay(value: string) {
  return value ? new Date(`${value}T23:59:59.999`).toISOString() : undefined;
}

function recordLink(log: AuditLog): string | null {
  if (!log.entity_id) return null;
  if (log.entity_type === "merchant") return `/admin/merchants/${log.entity_id}`;
  if (log.entity_type === "user") return `/admin/users/${log.entity_id}`;
  if (log.entity_type === "role") return `/admin/roles/${log.entity_id}`;
  return null;
}

function AuditLogDrawer({ id, actorName, onClose }: { id: string; actorName: (actorId: string | null) => string; onClose: () => void }) {
  const query = useQuery({
    queryKey: queryKeys.auditLogs.detail(id),
    queryFn: ({ signal }) => getAuditLog(id, signal)
  });
  const log = query.data;
  const link = log ? recordLink(log) : null;
  return (
    <Drawer
      open
      onClose={onClose}
      title={log ? auditEventLabel(log.event_type) : "Activity details"}
      footer={
        <Button variant="secondary" onClick={onClose}>
          Close
        </Button>
      }
    >
      {query.isLoading ? (
        <LoadingSkeleton rows={4} />
      ) : !log ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <div className="stack-lg">
          <DetailsPanel
            items={[
              { label: "Activity", value: auditEventLabel(log.event_type) },
              { label: "When", value: formatDateTime(log.created_at) },
              { label: "Performed by", value: actorName(log.actor_user_id) },
              { label: "Area", value: auditEntityLabel(log.entity_type) },
              { label: "Summary", value: log.message }
            ]}
          />
          {link ? (
            <Link to={link} className="btn btn--secondary" onClick={onClose}>
              Open the affected record
            </Link>
          ) : null}
          <div className="stack" style={{ gap: "var(--space-2)" }}>
            <h3 className="text-small text-muted">Reference for support</h3>
            <DetailsPanel
              items={[
                { label: "Activity reference", value: <span className="mono">{log.id}</span> },
                { label: "Record reference", value: log.entity_id ? <span className="mono">{log.entity_id}</span> : null }
              ]}
            />
          </div>
        </div>
      )}
    </Drawer>
  );
}

export function AuditLogsPage() {
  const auth = useAuth();
  const { values, page, setFilter, setPage, reset, hasFilters } = useUrlFilters(FILTERS);
  const [openEntry, setOpenEntry] = useState<string | null>(null);
  const canUsers = auth.can(PERMISSIONS.usersView);
  const dateError =
    values.from && values.to && values.from > values.to ? "The end date must be on or after the start date." : undefined;

  const params = {
    date_from: startOfDay(values.from),
    date_to: endOfDay(values.to),
    action: values.action || undefined,
    entity_type: values.area || undefined,
    actor_user_id: values.actor || undefined,
    page,
    page_size: PAGE_SIZE
  };
  const query = useQuery({
    queryKey: queryKeys.auditLogs.list(params),
    queryFn: ({ signal }) => listAuditLogs(params, signal),
    placeholderData: keepPreviousData,
    enabled: !dateError
  });

  // People list for readable names (first 100 accounts; others show as "Staff member").
  const peopleParams = { limit: 100, offset: 0 };
  const people = useQuery({
    queryKey: queryKeys.users.list(peopleParams),
    queryFn: ({ signal }) => listUsers(peopleParams, signal),
    enabled: canUsers,
    staleTime: 5 * 60_000
  });
  const names = new Map((people.data?.items ?? []).map((user) => [user.id, userDisplayName(user)]));
  const actorName = (actorId: string | null) => {
    if (!actorId) return "System";
    if (actorId === auth.user?.user_id) return "You";
    return names.get(actorId) ?? "Staff member";
  };

  const columns: Column<AuditLog>[] = [
    {
      key: "activity",
      header: "Activity",
      primary: true,
      render: (log) => (
        <div className="cell-primary__text">
          <button
            type="button"
            className="btn btn--link cell-primary__title"
            style={{ justifyContent: "flex-start", textAlign: "left" }}
            onClick={() => setOpenEntry(log.id)}
          >
            {auditEventLabel(log.event_type)}
          </button>
          <span className="cell-primary__subtitle">{log.message}</span>
        </div>
      )
    },
    { key: "area", header: "Area", render: (log) => auditEntityLabel(log.entity_type) },
    { key: "actor", header: "Performed by", render: (log) => actorName(log.actor_user_id) },
    {
      key: "when",
      header: "When",
      render: (log) => (
        <time dateTime={log.created_at} title={formatDateTime(log.created_at)} className="nowrap">
          {formatRelativeTime(log.created_at)}
        </time>
      )
    }
  ];

  return (
    <div className="page">
      <PageHeader
        title="Audit logs"
        description="A history of important changes made in MBGA. Verification codes and sign-in secrets are never shown here."
        breadcrumbs={[{ label: "Dashboard", to: "/admin/dashboard" }, { label: "Audit logs" }]}
        meta={<RefreshIndicator active={query.isFetching && !query.isLoading} />}
        actions={
          <Button variant="secondary" icon="refresh" onClick={() => void query.refetch()} disabled={query.isFetching}>
            Refresh
          </Button>
        }
      />
      <Card bodyless className="table-card">
        <FilterBar onReset={reset} canReset={hasFilters}>
          <Field label="From">
            <Input type="date" max={todayInputValue()} value={values.from} onChange={(event) => setFilter("from", event.target.value)} />
          </Field>
          <Field label="To" error={dateError}>
            <Input type="date" max={todayInputValue()} value={values.to} onChange={(event) => setFilter("to", event.target.value)} />
          </Field>
          <Field label="Activity">
            <Select
              value={values.action}
              onChange={(event) => setFilter("action", event.target.value)}
              options={AUDIT_EVENT_OPTIONS}
              placeholder="All activity"
            />
          </Field>
          <Field label="Area">
            <Select
              value={values.area}
              onChange={(event) => setFilter("area", event.target.value)}
              options={AUDIT_ENTITY_OPTIONS}
              placeholder="All areas"
            />
          </Field>
          {canUsers ? (
            <Field label="Performed by">
              <Select
                value={values.actor}
                onChange={(event) => setFilter("actor", event.target.value)}
                options={(people.data?.items ?? []).map((user) => ({ value: user.id, label: userDisplayName(user) }))}
                placeholder={people.isLoading ? "Loading…" : "Anyone"}
                disabled={people.isLoading}
              />
            </Field>
          ) : null}
        </FilterBar>
        {query.error && query.data ? (
          <div style={{ padding: "var(--space-4)" }}>
            <InlineError error={query.error} title="The list could not be refreshed" onRetry={() => void query.refetch()} />
          </div>
        ) : null}
        {dateError ? (
          <EmptyState icon="warning" title="Check the date range" description={dateError} />
        ) : (
          <DataTable
            caption="Audit log entries"
            columns={columns}
            rows={query.data?.items}
            getRowKey={(log) => log.id}
            isLoading={query.isLoading}
            error={query.error}
            onRetry={() => void query.refetch()}
            empty={
              hasFilters ? (
                <EmptyState icon="search" title="No activity matches your filters" description="Try a wider date range or clear the filters." />
              ) : (
                <EmptyState icon="history" title="No activity recorded yet" />
              )
            }
            footer={
              <Pagination
                page={page}
                pageSize={PAGE_SIZE}
                total={query.data?.total ?? 0}
                onPageChange={setPage}
                itemLabel="entries"
                disabled={query.isFetching}
              />
            }
          />
        )}
      </Card>
      <p className="meta">Free-text search and outcome filters are not available in the current backend release.</p>
      {openEntry ? <AuditLogDrawer id={openEntry} actorName={actorName} onClose={() => setOpenEntry(null)} /> : null}
    </div>
  );
}
