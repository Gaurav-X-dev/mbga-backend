import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { listAuditLogs } from "../../api/audit-logs.api";
import { getAdminDashboardSummary } from "../../api/dashboard.api";
import { listMerchants } from "../../api/merchants.api";
import { queryKeys } from "../../api/query-keys";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { ButtonLink } from "../../components/common/Button";
import { Icon, type IconName } from "../../components/common/Icon";
import { EmptyState, ErrorState, InlineError, RefreshIndicator, Skeleton } from "../../components/feedback/Feedback";
import { Card, PageHeader, StatCard } from "../../components/layout/Page";
import { formatDateTime, formatNumber, formatRelativeTime } from "../../utils/format";
import { auditEntityLabel, auditEventLabel } from "../../utils/labels";

const DASHBOARD_STALE = 60_000;

function useMerchantCount(status: "" | "ACTIVE" | "BLOCKED", enabled: boolean) {
  const params = { status: status || undefined, limit: 1, offset: 0 };
  return useQuery({
    queryKey: queryKeys.merchants.list(params),
    queryFn: ({ signal }) => listMerchants(params, signal),
    select: (data) => data.total,
    enabled,
    staleTime: DASHBOARD_STALE
  });
}

function StatValue({ value, isLoading }: { value: number | undefined; isLoading: boolean }) {
  if (isLoading) return <Skeleton width={64} height={32} />;
  return <>{formatNumber(value)}</>;
}

function Stat(props: {
  label: string;
  icon: IconName;
  value: number | undefined;
  isLoading: boolean;
  hint?: ReactNode;
  to?: string;
  linkLabel?: string;
  accent?: boolean;
}) {
  return (
    <StatCard
      label={props.label}
      icon={props.icon}
      accent={props.accent}
      value={<StatValue value={props.value} isLoading={props.isLoading} />}
      hint={props.hint}
      to={props.to}
      linkLabel={props.linkLabel}
    />
  );
}

export function DashboardPage() {
  const auth = useAuth();
  const canMerchants = auth.can(PERMISSIONS.merchantsView);
  const canAudit = auth.can(PERMISSIONS.auditLogsView);
  const canUsers = auth.can(PERMISSIONS.usersView);
  const canRoles = auth.can(PERMISSIONS.rolesView);

  const summary = useQuery({
    queryKey: queryKeys.adminDashboard.summary(),
    queryFn: ({ signal }) => getAdminDashboardSummary(signal),
    staleTime: DASHBOARD_STALE
  });
  const merchantsTotal = useMerchantCount("", canMerchants);
  const merchantsActive = useMerchantCount("ACTIVE", canMerchants);
  const merchantsBlocked = useMerchantCount("BLOCKED", canMerchants);
  const activityParams = { page: 1, page_size: 6 };
  const activity = useQuery({
    queryKey: queryKeys.auditLogs.list(activityParams),
    queryFn: ({ signal }) => listAuditLogs(activityParams, signal),
    enabled: canAudit,
    staleTime: DASHBOARD_STALE
  });

  const merchantError = merchantsTotal.error ?? merchantsActive.error ?? merchantsBlocked.error;
  const refreshing =
    (summary.isFetching && !summary.isLoading) || (merchantsTotal.isFetching && !merchantsTotal.isLoading);

  const blockedMerchants = merchantsBlocked.data ?? 0;
  const blockedUsers = summary.data?.blocked_users ?? 0;
  const attention: Array<{ label: string; to: string }> = [];
  if (canMerchants && blockedMerchants > 0) {
    attention.push({
      label: `${formatNumber(blockedMerchants)} merchant account${blockedMerchants === 1 ? " is" : "s are"} blocked`,
      to: "/admin/merchants?status=BLOCKED"
    });
  }
  if (canUsers && blockedUsers > 0) {
    attention.push({
      label: `${formatNumber(blockedUsers)} user account${blockedUsers === 1 ? " is" : "s are"} blocked`,
      to: "/admin/users?status=BLOCKED"
    });
  }

  const firstName = auth.user?.display_name?.split(" ")[0];

  return (
    <div className="page">
      <PageHeader
        title="Dashboard"
        description={firstName ? `Welcome back, ${firstName}. Here is today’s overview.` : "Here is today’s overview."}
        meta={<RefreshIndicator active={refreshing} />}
        actions={
          auth.can(PERMISSIONS.merchantsCreate) ? (
            <ButtonLink to="/admin/merchants/new" variant="accent" icon="plus">
              Add merchant
            </ButtonLink>
          ) : undefined
        }
      />

      {canMerchants ? (
        <section className="stack" aria-labelledby="merchants-heading">
          <h2 id="merchants-heading" className="section-title">
            Merchants
          </h2>
          {merchantError && merchantsTotal.data === undefined ? (
            <InlineError
              error={merchantError}
              title="Merchant figures could not be loaded"
              onRetry={() => {
                void merchantsTotal.refetch();
                void merchantsActive.refetch();
                void merchantsBlocked.refetch();
              }}
            />
          ) : (
            <div className="stat-grid">
              <Stat
                label="Total merchants"
                icon="store"
                accent
                value={merchantsTotal.data}
                isLoading={merchantsTotal.isLoading}
                to="/admin/merchants"
                linkLabel="View all merchants"
              />
              <Stat
                label="Active merchants"
                icon="checkCircle"
                value={merchantsActive.data}
                isLoading={merchantsActive.isLoading}
                to="/admin/merchants?status=ACTIVE"
                linkLabel="View active"
              />
              <Stat
                label="Blocked merchants"
                icon="ban"
                value={merchantsBlocked.data}
                isLoading={merchantsBlocked.isLoading}
                to="/admin/merchants?status=BLOCKED"
                linkLabel="View blocked"
              />
            </div>
          )}
        </section>
      ) : null}

      <section className="stack" aria-labelledby="access-heading">
        <h2 id="access-heading" className="section-title">
          Users and access
        </h2>
        {summary.error && !summary.data ? (
          <InlineError error={summary.error} title="Account figures could not be loaded" onRetry={() => void summary.refetch()} />
        ) : (
          <div className="stat-grid">
            <Stat
              label="Total users"
              icon="users"
              value={summary.data?.users}
              isLoading={summary.isLoading}
              hint={summary.data ? `${formatNumber(summary.data.active_users)} active` : undefined}
              to={canUsers ? "/admin/users" : undefined}
              linkLabel="View users"
            />
            <Stat
              label="Blocked users"
              icon="lock"
              value={summary.data?.blocked_users}
              isLoading={summary.isLoading}
              to={canUsers ? "/admin/users?status=BLOCKED" : undefined}
              linkLabel="View blocked users"
            />
            <Stat
              label="Active roles"
              icon="shield"
              value={summary.data?.active_roles}
              isLoading={summary.isLoading}
              hint={summary.data ? `${formatNumber(summary.data.roles)} roles in total` : undefined}
              to={canRoles ? "/admin/roles" : undefined}
              linkLabel="View roles"
            />
            <Stat
              label="Signed-in sessions"
              icon="devices"
              value={summary.data?.active_sessions}
              isLoading={summary.isLoading}
              hint="Sessions that have not been signed out"
            />
          </div>
        )}
      </section>

      <div className="grid-sidebar">
        {canAudit ? (
          <Card
            title="Recent activity"
            actions={
              <Link to="/admin/audit-logs" className="text-small">
                View all activity
              </Link>
            }
          >
            {activity.isLoading ? (
              <div className="stack" role="status">
                <span className="sr-only">Loading recent activity…</span>
                {[0, 1, 2, 3].map((index) => (
                  <Skeleton key={index} height={18} />
                ))}
              </div>
            ) : activity.error ? (
              <ErrorState error={activity.error} onRetry={() => void activity.refetch()} />
            ) : activity.data && activity.data.items.length > 0 ? (
              <ul className="list-plain">
                {activity.data.items.map((item) => (
                  <li key={item.id} className="activity-item">
                    <span className="activity-item__dot" aria-hidden="true" />
                    <div className="stack" style={{ gap: 2 }}>
                      <span style={{ fontWeight: 600 }}>{auditEventLabel(item.event_type)}</span>
                      <span className="meta">
                        {auditEntityLabel(item.entity_type)} ·{" "}
                        <time dateTime={item.created_at} title={formatDateTime(item.created_at)}>
                          {formatRelativeTime(item.created_at)}
                        </time>
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState icon="history" title="No activity yet" description="Changes made in the panel will appear here." />
            )}
          </Card>
        ) : null}

        <div className="stack-lg">
          <Card title="Needs attention">
            {summary.isLoading || merchantsBlocked.isLoading ? (
              <Skeleton height={18} />
            ) : attention.length > 0 ? (
              <ul className="shortcut-list list-plain">
                {attention.map((item) => (
                  <li key={item.to}>
                    <Link to={item.to} className="shortcut">
                      <Icon name="warning" />
                      <span>{item.label}</span>
                      <Icon name="chevronRight" />
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-muted text-small">
                <Icon name="checkCircle" size={16} /> Nothing needs your attention right now.
              </p>
            )}
          </Card>

          <Card title="Shortcuts">
            <ul className="shortcut-list list-plain">
              {auth.can(PERMISSIONS.merchantsCreate) ? (
                <li>
                  <Link to="/admin/merchants/new" className="shortcut">
                    <Icon name="store" />
                    Add a merchant
                    <Icon name="chevronRight" />
                  </Link>
                </li>
              ) : null}
              {canUsers ? (
                <li>
                  <Link to="/admin/users" className="shortcut">
                    <Icon name="users" />
                    Manage users
                    <Icon name="chevronRight" />
                  </Link>
                </li>
              ) : null}
              {canRoles ? (
                <li>
                  <Link to="/admin/roles" className="shortcut">
                    <Icon name="shield" />
                    Review roles and access
                    <Icon name="chevronRight" />
                  </Link>
                </li>
              ) : null}
              <li>
                <Link to="/admin/profile" className="shortcut">
                  <Icon name="user" />
                  My account
                  <Icon name="chevronRight" />
                </Link>
              </li>
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
