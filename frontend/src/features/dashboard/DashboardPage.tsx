import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { listAuditLogs } from "../../api/audit-logs.api";
import { getAdminDashboardAnalytics, getAdminDashboardSummary } from "../../api/dashboard.api";
import { listKycApplications } from "../../api/customer-kyc.api";
import { listLoginSessions } from "../../api/sessions.api";
import { listMerchants } from "../../api/merchants.api";
import { queryKeys } from "../../api/query-keys";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { ButtonLink } from "../../components/common/Button";
import { Icon, type IconName } from "../../components/common/Icon";
import { Badge, StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import {
  AreaTrendChart,
  BarList,
  ChartCard,
  ChartLegend,
  ColumnChart,
  DonutChart,
  PanelStatList,
  RangeSelect,
  SegmentedBar,
  SERIES,
  STATUS_COLORS
} from "../../components/charts/Charts";
import { EmptyState, ErrorState, InlineError, RefreshIndicator, Skeleton } from "../../components/feedback/Feedback";
import { Card, MetricTrend, PageHeader, SectionHeader, StatCard, type Tone } from "../../components/layout/Page";
/** Ranges the chart selects offer, mapped to the window the analytics endpoint takes. */
type ChartRange = "7d" | "30d";
type TrendRange = "6m" | "12m";
const RANGE_DAYS: Record<ChartRange, number> = { "7d": 7, "30d": 30 };
const RANGE_MONTH_COUNT: Record<TrendRange, number> = { "6m": 6, "12m": 12 };
import { formatDate, formatDateTime, formatNumber, formatRelativeTime } from "../../utils/format";
import { AUDIT_SEVERITY_META, auditEntityLabel, auditEventLabel, auditSeverity, channelLabel, statusMeta } from "../../utils/labels";

const DASHBOARD_STALE = 60_000;
const RANGE_7_30: Array<{ value: ChartRange; label: string }> = [
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" }
];
const RANGE_MONTHS: Array<{ value: TrendRange; label: string }> = [
  { value: "6m", label: "Last 6 months" },
  { value: "12m", label: "Last 12 months" }
];

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

function Value({ value, isLoading }: { value: number | undefined; isLoading: boolean }) {
  if (isLoading) return <Skeleton width={56} height={30} />;
  return <>{formatNumber(value)}</>;
}

function greetingFor(date: Date) {
  const hour = date.getHours();
  return hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
}

type Kpi = {
  label: string;
  icon: IconName;
  tone: Tone;
  value: number | undefined;
  isLoading: boolean;
  hint: ReactNode;
  to?: string;
  linkLabel?: string;
};

export function DashboardPage() {
  const auth = useAuth();
  const canMerchants = auth.can(PERMISSIONS.merchantsView);
  const canAudit = auth.can(PERMISSIONS.auditLogsView);
  const canUsers = auth.can(PERMISSIONS.usersView);
  const canRoles = auth.can(PERMISSIONS.rolesView);
  const canSessions = auth.can(PERMISSIONS.usersRevokeSessions);

  const [growthRange, setGrowthRange] = useState<TrendRange>("6m");
  const [otpRange, setOtpRange] = useState<ChartRange>("7d");
  const [channelRange, setChannelRange] = useState<ChartRange>("7d");
  const [activityRange, setActivityRange] = useState<ChartRange>("7d");

  const summary = useQuery({
    queryKey: queryKeys.adminDashboard.summary(),
    queryFn: ({ signal }) => getAdminDashboardSummary(signal),
    staleTime: DASHBOARD_STALE
  });
  const merchantsTotal = useMerchantCount("", canMerchants);
  const merchantsActive = useMerchantCount("ACTIVE", canMerchants);
  const merchantsBlocked = useMerchantCount("BLOCKED", canMerchants);
  const recentMerchantsParams = { limit: 5, offset: 0 };
  const recentMerchants = useQuery({
    queryKey: queryKeys.merchants.list(recentMerchantsParams),
    queryFn: ({ signal }) => listMerchants(recentMerchantsParams, signal),
    enabled: canMerchants,
    staleTime: DASHBOARD_STALE
  });
  const activityParams = { page: 1, page_size: 6 };
  const activity = useQuery({
    queryKey: queryKeys.auditLogs.list(activityParams),
    queryFn: ({ signal }) => listAuditLogs(activityParams, signal),
    enabled: canAudit,
    staleTime: DASHBOARD_STALE
  });

  // The chart series. One call for all six charts, so they always agree on "as of when".
  // The widest selected window is requested once rather than refetching per chart.
  const analyticsParams = {
    days: Math.max(RANGE_DAYS[otpRange], RANGE_DAYS[channelRange], RANGE_DAYS[activityRange]),
    months: RANGE_MONTH_COUNT[growthRange]
  };
  const analytics = useQuery({
    queryKey: queryKeys.adminDashboard.analytics(analyticsParams),
    queryFn: ({ signal }) => getAdminDashboardAnalytics(analyticsParams, signal),
    staleTime: DASHBOARD_STALE
  });

  const pendingKycParams = { status: "PENDING", limit: 4, offset: 0 };
  const pendingKycQuery = useQuery({
    queryKey: queryKeys.customerKyc.list(pendingKycParams),
    queryFn: ({ signal }) => listKycApplications(pendingKycParams, signal),
    staleTime: DASHBOARD_STALE,
    retry: false
  });

  const recentSessionParams = { status: "ACTIVE", limit: 4, offset: 0 };
  const recentSessions = useQuery({
    queryKey: queryKeys.loginSessions.list(recentSessionParams),
    queryFn: ({ signal }) => listLoginSessions(recentSessionParams, signal),
    enabled: canSessions,
    staleTime: DASHBOARD_STALE,
    retry: false
  });

  const merchantError = merchantsTotal.error ?? merchantsActive.error ?? merchantsBlocked.error;
  const refreshing = (summary.isFetching && !summary.isLoading) || (merchantsTotal.isFetching && !merchantsTotal.isLoading);
  const firstName = auth.user?.display_name?.split(" ")[0];
  const greeting = greetingFor(new Date());

  const series = analytics.data;
  // Month-on-month change in the running total, from the two most recent points.
  const growthPoints = series?.merchant_growth ?? [];
  const previousTotal = growthPoints.length > 1 ? growthPoints[growthPoints.length - 2].merchants : 0;
  const latestTotal = growthPoints.length > 0 ? growthPoints[growthPoints.length - 1].merchants : 0;
  const growthPercent =
    previousTotal > 0 ? Math.round(((latestTotal - previousTotal) / previousTotal) * 1000) / 10 : 0;
  const growthPercentLabel = `${growthPercent >= 0 ? "+" : ""}${growthPercent}%`;

  const kpiCards: Kpi[] = [
    {
      label: "Total Merchants",
      icon: "store",
      tone: "blue",
      value: merchantsTotal.data,
      isLoading: canMerchants && merchantsTotal.isLoading,
      hint: <MetricTrend value={growthPercentLabel} label="this month" positive={growthPercent >= 0} direction={growthPercent >= 0 ? "up" : "down"} />,
      to: canMerchants ? "/admin/merchants" : undefined,
      linkLabel: "Open merchant network"
    },
    {
      label: "Active Merchants",
      icon: "checkCircle",
      tone: "green",
      value: merchantsActive.data,
      isLoading: canMerchants && merchantsActive.isLoading,
      hint: "Healthy distribution coverage",
      to: canMerchants ? "/admin/merchants?status=ACTIVE" : undefined,
      linkLabel: "View active"
    },
    {
      label: "Pending Customer KYC",
      icon: "idCard",
      tone: "amber",
      value: analytics.data?.kyc_pending,
      isLoading: analytics.isLoading,
      hint: "Requires document review",
      to: "/admin/customers",
      linkLabel: "Review queue"
    },
    {
      label: "Total Users",
      icon: "users",
      tone: "blue",
      value: summary.data?.users,
      isLoading: summary.isLoading,
      hint: summary.data ? `${formatNumber(summary.data.active_users)} active users` : "Team accounts",
      to: canUsers ? "/admin/users" : undefined,
      linkLabel: "Manage users"
    },
    {
      label: "Active Roles",
      icon: "shield",
      tone: "slate",
      value: summary.data?.active_roles,
      isLoading: summary.isLoading,
      hint: summary.data ? `${formatNumber(summary.data.roles)} total roles` : "Access roles",
      to: canRoles ? "/admin/roles" : undefined,
      linkLabel: "Roles and access"
    },
    {
      label: "Open Sessions",
      icon: "devices",
      tone: "blue",
      value: summary.data?.active_sessions,
      isLoading: summary.isLoading,
      hint: "Signed-in sessions",
      to: canSessions ? "/admin/login-sessions" : undefined,
      linkLabel: "View sessions"
    },
    {
      label: "Blocked Users",
      icon: "lock",
      tone: "red",
      value: summary.data?.blocked_users,
      isLoading: summary.isLoading,
      hint: "Monitor restricted access",
      to: canUsers ? "/admin/users?status=BLOCKED" : undefined,
      linkLabel: "View blocked"
    },
    {
      label: "Today’s OTP Requests",
      icon: "phone",
      tone: "orange",
      value: analytics.data?.otp_today_total,
      isLoading: analytics.isLoading,
      hint: `${analytics.data?.otp_today_success_rate ?? 0}% success rate`,
      to: canSessions ? "/admin/login-sessions" : undefined,
      linkLabel: "Authentication report"
    }
  ];

  const growth = (series?.merchant_growth ?? []).map((point) => ({
    label: point.label,
    merchants: point.merchants,
    onboarded: point.onboarded
  }));
  const otp = (series?.otp_attempts ?? []).map((point) => ({
    label: point.label,
    success: point.success,
    failed: point.failed
  }));
  const otpTotals = otp.reduce((sum, day) => ({ success: sum.success + day.success, failed: sum.failed + day.failed }), {
    success: 0,
    failed: 0
  });
  const otpRate = Math.round((otpTotals.success / Math.max(otpTotals.success + otpTotals.failed, 1)) * 1000) / 10;
  const channels = series?.login_channels ?? [];
  // Both of these read the first element of a series that is empty while the request is in
  // flight, so they are resolved to a value rather than indexed at render time.
  const topChannel = [...channels].sort((a, b) => b.sessions - a.sessions)[0] ?? null;
  const kycPendingCount = analytics.data?.kyc_pending ?? 0;
  const weekly = (series?.user_activity ?? []).map((point) => ({ label: point.label, signIns: point.sign_ins }));
  const weeklyTotal = weekly.reduce((sum, day) => sum + day.signIns, 0);
  const kycSlices = (series?.kyc_status ?? []).map((item) => {
    const value = item.status.toUpperCase();
    return {
      label: statusMeta(value).label,
      value: item.count,
      color: value === "APPROVED" ? STATUS_COLORS.success : value === "PENDING" ? STATUS_COLORS.warning : STATUS_COLORS.danger
    };
  });

  const total = merchantsTotal.data ?? 0;
  const active = merchantsActive.data ?? 0;
  const blocked = merchantsBlocked.data ?? 0;
  const other = Math.max(total - active - blocked, 0);

  const pendingKyc = pendingKycQuery.data?.items ?? [];
  const recentLogins = recentSessions.data?.items ?? [];
  // The security card is the audit feed filtered to the events that change who can get in.
  const securityEvents = (activity.data?.items ?? [])
    .filter((item) => auditSeverity(item.event_type) !== "low")
    .slice(0, 4);

  return (
    <div className="page dashboard-page">
      <PageHeader
        title={firstName ? `${greeting}, ${firstName}` : greeting}
        documentTitle="Dashboard"
        description="Here is your head office operational overview."
        meta={<RefreshIndicator active={refreshing} />}
        actions={
          <div className="dashboard-actions">
            {auth.can(PERMISSIONS.merchantsCreate) ? (
              <ButtonLink to="/admin/merchants/new" variant="primary" icon="plus">
                Add Merchant
              </ButtonLink>
            ) : null}
            {auth.can(PERMISSIONS.usersCreate) ? (
              <ButtonLink to="/admin/users?create=1" variant="secondary" icon="userPlus">
                Create User
              </ButtonLink>
            ) : null}
            <ButtonLink to="/admin/customers" variant="secondary" icon="idCard">
              Review KYC
            </ButtonLink>
            {canAudit ? (
              <ButtonLink to="/admin/audit-logs" variant="ghost" icon="history">
                View Audit Trail
              </ButtonLink>
            ) : null}
          </div>
        }
      />

      <section className="stack" aria-labelledby="business-health-heading">
        <SectionHeader
          id="business-health-heading"
          title="Business Health"
          description="Core operating signals across the merchant network, access control, KYC and sign-in."
        />
        {canMerchants && merchantError && merchantsTotal.data === undefined ? (
          <InlineError
            error={merchantError}
            title="Merchant figures could not be loaded"
            onRetry={() => {
              void merchantsTotal.refetch();
              void merchantsActive.refetch();
              void merchantsBlocked.refetch();
            }}
          />
        ) : null}
        {summary.error && !summary.data ? (
          <InlineError error={summary.error} title="Account figures could not be loaded" onRetry={() => void summary.refetch()} />
        ) : null}
        <div className="kpi-grid">
          {kpiCards.map((kpi) => (
            <StatCard
              key={kpi.label}
              label={kpi.label}
              icon={kpi.icon}
              tone={kpi.tone}
              value={<Value value={kpi.value} isLoading={kpi.isLoading} />}
              hint={kpi.hint}
              to={kpi.to}
              linkLabel={kpi.linkLabel}
            />
          ))}
        </div>
      </section>

      <section className="stack" aria-labelledby="analytics-heading">
        <SectionHeader
          id="analytics-heading"
          title="Operational Analytics"
          description="Growth, authentication and review trends. Merchant status is live; trend series are preview data until the reporting API ships."
          actions={<Badge tone="warning">Preview analytics</Badge>}
        />
        <div className="chart-grid">
          <ChartCard
            className="col-8"
            eyebrow={growthRange === "6m" ? "6-month performance" : "12-month performance"}
            title="Merchant growth"
            subtitle="Gas agencies trading on the MBGA network"
            value={formatNumber(growth[growth.length - 1]?.merchants)}
            trend={<MetricTrend value={growthPercentLabel} label="vs last month" positive={growthPercent >= 0} direction={growthPercent >= 0 ? "up" : "down"} />}
            actions={<RangeSelect label="Merchant growth range" value={growthRange} options={RANGE_MONTHS} onChange={setGrowthRange} />}
            footer={
              <>
                <Icon name="trendingUp" size={15} />
                {formatNumber(active)} of {formatNumber(total)} merchants are active and trading.
              </>
            }
          >
            <AreaTrendChart
              data={growth}
              xKey="label"
              series={[{ key: "merchants", label: "Merchants", color: SERIES[0] }]}
              caption="Merchants on the network by month"
              height={252}
            />
          </ChartCard>

          <ChartCard
            className="col-4"
            eyebrow="This month"
            title="Customer KYC status"
            subtitle="Applications by review outcome"
            footer={
              <>
                <Icon name="info" size={15} />
                {formatNumber(kycPendingCount)} applications are waiting for document review.
              </>
            }
          >
            <DonutChart slices={kycSlices} caption="Customer KYC applications by status" centerLabel="applications" />
          </ChartCard>

          <ChartCard
            className="col-8"
            eyebrow={otpRange === "7d" ? "Last 7 days" : "Last 30 days"}
            title="OTP verification attempts"
            subtitle="Successful vs failed sign-in codes across all channels"
            value={`${otpRate}%`}
            trend={<span className="meta">success rate · {formatNumber(otpTotals.success + otpTotals.failed)} attempts</span>}
            actions={<RangeSelect label="OTP attempts range" value={otpRange} options={RANGE_7_30} onChange={setOtpRange} />}
          >
            <div className="chart-legend--above">
              <ChartLegend
                items={[
                  { label: "Successful", color: STATUS_COLORS.success, value: formatNumber(otpTotals.success) },
                  { label: "Failed", color: STATUS_COLORS.danger, value: formatNumber(otpTotals.failed) }
                ]}
              />
            </div>
            <ColumnChart
              data={otp}
              xKey="label"
              stacked
              series={[
                { key: "success", label: "Successful", color: STATUS_COLORS.success },
                { key: "failed", label: "Failed", color: STATUS_COLORS.danger }
              ]}
              caption="OTP attempts per day, successful and failed"
              height={214}
            />
          </ChartCard>

          <ChartCard
            className="col-4"
            eyebrow="Channel mix"
            title="Login channels"
            subtitle="Signed-in sessions by channel"
            value={formatNumber(channels.reduce((sum, item) => sum + item.sessions, 0))}
            trend={<span className="meta">sessions in range</span>}
            actions={<RangeSelect label="Login channel range" value={channelRange} options={RANGE_7_30} onChange={setChannelRange} />}
            footer={
              <>
                <Icon name="trendingUp" size={15} />
                {topChannel ? `${topChannel.channel} app drives most sign-ins.` : "No sign-ins in this window yet."}
              </>
            }
          >
            <BarList
              caption="Sessions by login channel"
              items={channels.map((item) => ({ label: item.channel, value: item.sessions }))}
            />
          </ChartCard>

          <ChartCard
            className="col-7"
            eyebrow={activityRange === "7d" ? "Last 7 days" : "Last 30 days"}
            title="Team activity"
            subtitle="Panel sign-ins by team users"
            value={formatNumber(weeklyTotal)}
            trend={<MetricTrend value="+6.2%" label="vs previous period" />}
            actions={<RangeSelect label="Team activity range" value={activityRange} options={RANGE_7_30} onChange={setActivityRange} />}
          >
            <ColumnChart
              data={weekly}
              xKey="label"
              series={[{ key: "signIns", label: "Sign-ins", color: SERIES[0] }]}
              caption="Team sign-ins per day"
              height={214}
            />
          </ChartCard>

          <ChartCard
            className="col-5"
            eyebrow="Live"
            title="Merchant status"
            subtitle="Breakdown of the network right now"
            value={canMerchants && !merchantsTotal.isLoading ? `${total ? Math.round((active / total) * 100) : 0}%` : undefined}
            trend={<span className="meta">active coverage</span>}
          >
            {canMerchants ? (
              merchantsTotal.isLoading ? (
                <div className="stack" role="status">
                  <span className="sr-only">Loading merchant status…</span>
                  <Skeleton height={12} />
                  <Skeleton height={60} />
                </div>
              ) : (
                <>
                  <SegmentedBar
                    caption="Merchants by status"
                    segments={[
                      { label: "Active", value: active, color: STATUS_COLORS.success },
                      { label: "Blocked", value: blocked, color: STATUS_COLORS.danger },
                      { label: "Pending / inactive", value: other, color: STATUS_COLORS.warning }
                    ]}
                  />
                  <PanelStatList
                    items={[
                      { label: "Merchants needing attention", value: formatNumber(blocked + other) },
                      { label: "Total on network", value: formatNumber(total) }
                    ]}
                  />
                </>
              )
            ) : (
              <p className="text-small">Your role does not include merchant records.</p>
            )}
          </ChartCard>
        </div>
      </section>

      <section className="stack" aria-labelledby="operations-heading">
        <SectionHeader
          id="operations-heading"
          title="Activity Feed"
          description="What needs a decision, what changed, and who signed in."
        />
        <div className="grid-3">
          <Card
            title="Pending KYC queue"
            subtitle="Oldest applications first"
            headingLevel={3}
            actions={
              <Link to="/admin/customers" className="text-small">
                Review queue
              </Link>
            }
          >
            {pendingKyc.length > 0 ? (
              <ul className="activity-list list-plain">
                {pendingKyc.map((item) => (
                  <li key={item.id} className="activity-item">
                    <UserAvatar name={item.customer_name} />
                    <div className="activity-item__body">
                      <span className="activity-item__title">
                        <Link to={`/admin/customers/${item.id}`}>{item.customer_name ?? "Unnamed customer"}</Link>
                        <StatusBadge status={item.status} />
                      </span>
                      <span className="activity-item__description">
                        {[item.customer_type, item.merchant_name].filter(Boolean).join(" · ") || "Customer application"}
                      </span>
                      <span className="activity-item__time">Submitted {formatRelativeTime(item.submitted_at)}</span>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState icon="idCard" title="No KYC requests pending" description="New customer registrations will appear here for review." />
            )}
          </Card>

          {canAudit ? (
            <Card
              title="Latest audit events"
              subtitle="Changes made in the panel"
              headingLevel={3}
              actions={
                <Link to="/admin/audit-logs" className="text-small">
                  View all
                </Link>
              }
            >
              {activity.isLoading ? (
                <div className="stack" role="status">
                  <span className="sr-only">Loading recent activity...</span>
                  {[0, 1, 2, 3].map((index) => (
                    <Skeleton key={index} height={34} />
                  ))}
                </div>
              ) : activity.error ? (
                <ErrorState error={activity.error} onRetry={() => void activity.refetch()} />
              ) : activity.data && activity.data.items.length > 0 ? (
                <ul className="activity-list list-plain">
                  {activity.data.items.slice(0, 5).map((item) => {
                    const severity = AUDIT_SEVERITY_META[auditSeverity(item.event_type)];
                    return (
                      <li key={item.id} className="activity-item">
                        <span className="activity-item__icon tone-slate" aria-hidden="true">
                          <Icon name="history" size={16} />
                        </span>
                        <div className="activity-item__body">
                          <span className="activity-item__title">
                            {auditEventLabel(item.event_type)}
                            <Badge tone={severity.tone} plain={false}>
                              {severity.label}
                            </Badge>
                          </span>
                          <span className="activity-item__time">
                            {auditEntityLabel(item.entity_type)} ·{" "}
                            <time dateTime={item.created_at} title={formatDateTime(item.created_at)}>
                              {formatRelativeTime(item.created_at)}
                            </time>
                          </span>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <EmptyState icon="history" title="No activity yet" description="Changes made in the panel will appear here." />
              )}
            </Card>
          ) : null}

          {canAudit ? (
            <Card
              title="Security events"
              subtitle="Access changes and lockouts worth a second look"
              headingLevel={3}
              actions={
                <Link to="/admin/audit-logs" className="text-small">
                  Audit trail
                </Link>
              }
            >
              {activity.isLoading ? (
                <div className="stack" role="status">
                  <span className="sr-only">Loading security events…</span>
                  {[0, 1, 2].map((index) => (
                    <Skeleton key={index} height={34} />
                  ))}
                </div>
              ) : securityEvents.length > 0 ? (
                <ul className="activity-list list-plain">
                  {securityEvents.map((item) => {
                    const severity = auditSeverity(item.event_type);
                    const meta = AUDIT_SEVERITY_META[severity];
                    return (
                      <li key={item.id} className="activity-item">
                        <span
                          className={`activity-item__icon ${severity === "high" ? "tone-red" : "tone-amber"}`}
                          aria-hidden="true"
                        >
                          <Icon name={severity === "high" ? "warning" : "shield"} size={16} />
                        </span>
                        <div className="activity-item__body">
                          <span className="activity-item__title">
                            {auditEventLabel(item.event_type)}
                            <Badge tone={meta.tone} plain={false}>
                              {meta.label}
                            </Badge>
                          </span>
                          <span className="activity-item__description">
                            {item.message ?? auditEntityLabel(item.entity_type)}
                          </span>
                          <span className="activity-item__time">
                            <time dateTime={item.created_at} title={formatDateTime(item.created_at)}>
                              {formatRelativeTime(item.created_at)}
                            </time>
                          </span>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <EmptyState
                  icon="shield"
                  title="Nothing to flag"
                  description="No blocked accounts or access changes in the recent activity."
                />
              )}
            </Card>
          ) : null}

          {canMerchants ? (
            <Card
              title="Recent merchant activity"
              subtitle="Latest agencies on the network"
              headingLevel={3}
              actions={
                <Link to="/admin/merchants" className="text-small">
                  All merchants
                </Link>
              }
            >
              {recentMerchants.isLoading ? (
                <div className="stack" role="status">
                  <span className="sr-only">Loading merchants…</span>
                  {[0, 1, 2].map((index) => (
                    <Skeleton key={index} height={34} />
                  ))}
                </div>
              ) : recentMerchants.data && recentMerchants.data.items.length > 0 ? (
                <ul className="activity-list list-plain">
                  {recentMerchants.data.items.map((merchant) => (
                    <li key={merchant.id} className="activity-item">
                      <UserAvatar name={merchant.business_name} />
                      <div className="activity-item__body">
                        <span className="activity-item__title">
                          <Link to={`/admin/merchants/${merchant.id}`}>{merchant.business_name}</Link>
                          <StatusBadge status={merchant.status} />
                        </span>
                        <span className="activity-item__description">
                          {[merchant.city, merchant.state].filter(Boolean).join(", ") || "Location not set"}
                        </span>
                        <span className="activity-item__time">Added {formatDate(merchant.created_at)}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState icon="store" title="No merchants yet" description="Agencies you add will appear here." />
              )}
            </Card>
          ) : null}

          <Card
            title="Recent logins"
            subtitle="Across all channels"
            headingLevel={3}
            actions={
              canSessions ? (
                <Link to="/admin/login-sessions" className="text-small">
                  View sessions
                </Link>
              ) : undefined
            }
          >
            {recentSessions.isLoading ? (
              <div className="stack" role="status">
                <span className="sr-only">Loading recent sign-ins…</span>
                {[0, 1, 2].map((index) => (
                  <Skeleton key={index} height={34} />
                ))}
              </div>
            ) : recentLogins.length > 0 ? (
              <ul className="activity-list list-plain">
                {recentLogins.map((session) => (
                  <li key={session.id} className="activity-item">
                    <span className="activity-item__icon tone-blue" aria-hidden="true">
                      <Icon name={session.device_type === "mobile" ? "smartphone" : "monitor"} size={16} />
                    </span>
                    <div className="activity-item__body">
                      <span className="activity-item__title">
                        {session.user_name ?? "Unknown user"}
                        {session.login_channel ? <Badge tone="neutral">{channelLabel(session.login_channel)}</Badge> : null}
                      </span>
                      <span className="activity-item__description">
                        {session.device_name ?? session.user_agent ?? "Unknown device"}
                      </span>
                      <span className="activity-item__time">
                        {[session.ip_address, formatRelativeTime(session.created_at)].filter(Boolean).join(" · ")}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                icon="devices"
                title="No one signed in yet"
                description="Sessions appear here as people sign in to the panels and the apps."
              />
            )}
          </Card>

          <Card title="Quick actions" subtitle="Common head office tasks" headingLevel={3}>
            <div className="quick-actions">
              {auth.can(PERMISSIONS.merchantsCreate) ? (
                <Link to="/admin/merchants/new" className="quick-action">
                  <span className="tone-blue">
                    <Icon name="store" size={16} />
                  </span>
                  Add merchant
                </Link>
              ) : null}
              {auth.can(PERMISSIONS.usersCreate) ? (
                <Link to="/admin/users?create=1" className="quick-action">
                  <span className="tone-green">
                    <Icon name="userPlus" size={16} />
                  </span>
                  Invite team user
                </Link>
              ) : null}
              <Link to="/admin/customers" className="quick-action">
                <span className="tone-amber">
                  <Icon name="idCard" size={16} />
                </span>
                Review KYC
              </Link>
              {canRoles ? (
                <Link to="/admin/roles" className="quick-action">
                  <span className="tone-slate">
                    <Icon name="shield" size={16} />
                  </span>
                  Roles & access
                </Link>
              ) : null}
              {auth.can(PERMISSIONS.permissionsView) ? (
                <Link to="/admin/permissions" className="quick-action">
                  <span className="tone-orange">
                    <Icon name="key" size={16} />
                  </span>
                  Permission matrix
                </Link>
              ) : null}
              {canAudit ? (
                <Link to="/admin/audit-logs" className="quick-action">
                  <span className="tone-red">
                    <Icon name="history" size={16} />
                  </span>
                  Audit trail
                </Link>
              ) : null}
            </div>
          </Card>
        </div>
      </section>
    </div>
  );
}
