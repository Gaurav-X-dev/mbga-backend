import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { getAuditLog, listAuditLogs, type AuditLog } from "../../api/audit-logs.api";
import { queryKeys } from "../../api/query-keys";
import { listUsers } from "../../api/users.api";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { Badge, UserAvatar } from "../../components/common/StatusBadge";
import { DetailDrawer, DrawerSection } from "../../components/feedback/Dialogs";
import { EmptyState, ErrorState, InlineError, LoadingSkeleton, RefreshIndicator } from "../../components/feedback/Feedback";
import { Field, Input, SearchInput, Select } from "../../components/forms/Field";
import { Card, DetailsPanel, PageHeader } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, TableHeader, type Column } from "../../components/tables/DataTable";
import { downloadCsv } from "../../utils/csv";
import { useUrlFilters } from "../../hooks/useUrlFilters";
import { formatDateTime, formatRelativeTime, todayInputValue } from "../../utils/format";
import {
  AUDIT_ENTITY_OPTIONS,
  AUDIT_EVENT_OPTIONS,
  AUDIT_SEVERITY_META,
  auditActionLabel,
  auditEntityLabel,
  auditEventLabel,
  auditSeverity,
  type AuditSeverity
} from "../../utils/labels";
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

function SeverityBadge({ eventType }: { eventType: string }) {
  const meta = AUDIT_SEVERITY_META[auditSeverity(eventType)];
  return (
    <Badge tone={meta.tone} plain={false}>
      {meta.label}
    </Badge>
  );
}

/** Pretty-printed JSON with light syntax colouring; values are text nodes, never HTML. */
function JsonView({ value }: { value: unknown }) {
  const lines = JSON.stringify(value, null, 2).split("\n");
  return (
    <pre className="code-block">
      {lines.map((line, index) => {
        const match = /^(\s*)("[^"]+")(:\s*)(.*)$/.exec(line);
        let content: ReactNode = line;
        if (match) {
          const [, indent, key, colon, rest] = match;
          const valueClass = rest.startsWith('"') ? "s" : rest === "null" || rest === "null," ? undefined : "n";
          content = (
            <>
              {indent}
              <span className="k">{key}</span>
              {colon}
              <span className={valueClass}>{rest}</span>
            </>
          );
        }
        return (
          <span key={index}>
            {content}
            {"\n"}
          </span>
        );
      })}
    </pre>
  );
}

function AuditLogDrawer({ id, actorName, onClose }: { id: string; actorName: (actorId: string | null) => string; onClose: () => void }) {
  const query = useQuery({
    queryKey: queryKeys.auditLogs.detail(id),
    queryFn: ({ signal }) => getAuditLog(id, signal)
  });
  const log = query.data;
  const link = log ? recordLink(log) : null;
  return (
    <DetailDrawer
      open
      size="lg"
      onClose={onClose}
      title={log ? auditEventLabel(log.event_type) : "Activity details"}
      subtitle={log ? formatDateTime(log.created_at) : undefined}
      meta={
        log ? (
          <>
            <SeverityBadge eventType={log.event_type} />
            <Badge tone="neutral">{auditEntityLabel(log.entity_type)}</Badge>
          </>
        ) : undefined
      }
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          {link ? (
            <Link to={link} className="btn btn--primary" onClick={onClose}>
              Open the affected record
            </Link>
          ) : null}
        </>
      }
    >
      {query.isLoading ? (
        <LoadingSkeleton rows={4} />
      ) : !log ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          <DrawerSection title="Event summary">
            <p>{log.message ?? auditEventLabel(log.event_type)}</p>
            <DetailsPanel
              items={[
                { label: "Event", value: auditEventLabel(log.event_type) },
                { label: "Action", value: auditActionLabel(log.event_type) },
                { label: "Module", value: auditEntityLabel(log.entity_type) },
                { label: "Severity", value: AUDIT_SEVERITY_META[auditSeverity(log.event_type)].label }
              ]}
            />
          </DrawerSection>
          <DrawerSection title="Related user & time">
            <DetailsPanel
              items={[
                { label: "Performed by", value: actorName(log.actor_user_id) },
                { label: "When", value: `${formatDateTime(log.created_at)} (${formatRelativeTime(log.created_at)})` }
              ]}
            />
          </DrawerSection>
          <DrawerSection title="Changes">
            <p className="text-small text-muted">
              This event records what happened, not field-by-field before and after values. Open the affected record to see its
              current state.
            </p>
          </DrawerSection>
          <DrawerSection title="Metadata">
            <JsonView
              value={{
                id: log.id,
                event_type: log.event_type,
                entity_type: log.entity_type,
                entity_id: log.entity_id,
                actor_user_id: log.actor_user_id,
                created_at: log.created_at
              }}
            />
          </DrawerSection>
        </>
      )}
    </DetailDrawer>
  );
}

export function AuditLogsPage() {
  const auth = useAuth();
  const { values, page, setFilter, setPage, reset, hasFilters } = useUrlFilters(FILTERS);
  const [openEntry, setOpenEntry] = useState<string | null>(null);
  const [pageSearch, setPageSearch] = useState("");
  const [severity, setSeverity] = useState<"" | AuditSeverity>("");
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

  const term = pageSearch.trim().toLowerCase();
  const rows = query.data?.items.filter(
    (log) =>
      (!severity || auditSeverity(log.event_type) === severity) &&
      (!term ||
        auditEventLabel(log.event_type).toLowerCase().includes(term) ||
        (log.message ?? "").toLowerCase().includes(term) ||
        actorName(log.actor_user_id).toLowerCase().includes(term))
  );
  const localFilters = Boolean(term || severity);

  const columns: Column<AuditLog>[] = [
    {
      key: "activity",
      header: "Event",
      primary: true,
      render: (log) => (
        <div className="cell-primary__text">
          <button type="button" className="btn btn--link cell-primary__title" onClick={() => setOpenEntry(log.id)}>
            {auditEventLabel(log.event_type)}
          </button>
          <span className="cell-primary__subtitle">{log.message}</span>
        </div>
      )
    },
    {
      key: "actor",
      header: "User",
      sortValue: (log) => actorName(log.actor_user_id),
      render: (log) => (
        <span className="row" style={{ flexWrap: "nowrap", gap: 8 }}>
          <UserAvatar name={actorName(log.actor_user_id)} />
          <span>{actorName(log.actor_user_id)}</span>
        </span>
      )
    },
    { key: "area", header: "Module", sortValue: (log) => auditEntityLabel(log.entity_type), render: (log) => auditEntityLabel(log.entity_type) },
    { key: "action", header: "Action", render: (log) => <Badge tone="neutral">{auditActionLabel(log.event_type)}</Badge> },
    {
      key: "when",
      header: "Time",
      sortValue: (log) => log.created_at,
      render: (log) => (
        <time dateTime={log.created_at} title={formatDateTime(log.created_at)} className="cell-stack">
          <span className="nowrap">{formatRelativeTime(log.created_at)}</span>
          <small className="nowrap">{formatDateTime(log.created_at)}</small>
        </time>
      )
    },
    {
      key: "severity",
      header: "Severity",
      sortValue: (log) => ["high", "medium", "low"].indexOf(auditSeverity(log.event_type)),
      render: (log) => <SeverityBadge eventType={log.event_type} />
    }
  ];

  function resetAll() {
    reset();
    setPageSearch("");
    setSeverity("");
  }

  return (
    <div className="page list-page">
      <PageHeader
        title="Audit Trail"
        documentTitle="Audit Trail"
        description="Track sensitive activity across the admin panel. Verification codes and sign-in secrets are never recorded."
        meta={<RefreshIndicator active={query.isFetching && !query.isLoading} />}
        actions={
          <>
            <Button
              variant="secondary"
              icon="download"
              disabled={!rows?.length}
              onClick={() =>
                downloadCsv(
                  "mbga-audit-trail.csv",
                  ["Time", "Event", "Summary", "User", "Module", "Action", "Severity", "Reference"],
                  (rows ?? []).map((log) => [
                    formatDateTime(log.created_at),
                    auditEventLabel(log.event_type),
                    log.message,
                    actorName(log.actor_user_id),
                    auditEntityLabel(log.entity_type),
                    auditActionLabel(log.event_type),
                    AUDIT_SEVERITY_META[auditSeverity(log.event_type)].label,
                    log.id
                  ])
                )
              }
            >
              Export
            </Button>
            <Button variant="secondary" icon="refresh" onClick={() => void query.refetch()} disabled={query.isFetching}>
              Refresh
            </Button>
          </>
        }
      />
      <Card bodyless className="table-card">
        <TableHeader title="Activity log" count={query.data?.total} description="Newest first. Select an event for its full record." />
        <FilterBar onReset={resetAll} canReset={hasFilters || localFilters}>
          <SearchInput
            label="Search this page"
            placeholder="Search events on this page"
            value={pageSearch}
            onChange={(event) => setPageSearch(event.target.value)}
          />
          <Field label="Area" hideLabel>
            <Select value={values.area} onChange={(event) => setFilter("area", event.target.value)} options={AUDIT_ENTITY_OPTIONS} placeholder="All modules" />
          </Field>
          <Field label="Activity" hideLabel>
            <Select value={values.action} onChange={(event) => setFilter("action", event.target.value)} options={AUDIT_EVENT_OPTIONS} placeholder="All actions" />
          </Field>
          {canUsers ? (
            <Field label="Performed by" hideLabel>
              <Select
                value={values.actor}
                onChange={(event) => setFilter("actor", event.target.value)}
                options={(people.data?.items ?? []).map((user) => ({ value: user.id, label: userDisplayName(user) }))}
                placeholder={people.isLoading ? "Loading…" : "Any user"}
                disabled={people.isLoading}
              />
            </Field>
          ) : null}
          <Field label="Severity" hideLabel>
            <Select
              value={severity}
              onChange={(event) => setSeverity(event.target.value as "" | AuditSeverity)}
              placeholder="Any severity"
              options={[
                { value: "high", label: "High" },
                { value: "medium", label: "Medium" },
                { value: "low", label: "Low" }
              ]}
            />
          </Field>
          <Field label="From">
            <Input type="date" max={todayInputValue()} value={values.from} onChange={(event) => setFilter("from", event.target.value)} />
          </Field>
          <Field label="To" error={dateError}>
            <Input type="date" max={todayInputValue()} value={values.to} onChange={(event) => setFilter("to", event.target.value)} />
          </Field>
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
            rows={rows}
            getRowKey={(log) => log.id}
            onRowClick={(log) => setOpenEntry(log.id)}
            isSelected={(log) => log.id === openEntry}
            isLoading={query.isLoading}
            error={query.error}
            onRetry={() => void query.refetch()}
            empty={
              hasFilters || localFilters ? (
                <EmptyState
                  icon="search"
                  title="No activity matches your filters"
                  description={localFilters ? "Search and severity apply to the events on this page." : "Try a wider date range or clear the filters."}
                />
              ) : (
                <EmptyState icon="history" title="No activity recorded yet" description="Changes made in the panel will appear here." />
              )
            }
            footer={
              <Pagination
                page={page}
                pageSize={PAGE_SIZE}
                total={query.data?.total ?? 0}
                onPageChange={setPage}
                itemLabel="events"
                disabled={query.isFetching}
              />
            }
          />
        )}
      </Card>
      {openEntry ? <AuditLogDrawer id={openEntry} actorName={actorName} onClose={() => setOpenEntry(null)} /> : null}
    </div>
  );
}
