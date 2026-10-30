import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { queryKeys } from "../../api/query-keys";
import { getReport, type ReportType } from "../../api/reports.api";
import { Icon, type IconName } from "../../components/common/Icon";
import { InlineError, Skeleton } from "../../components/feedback/Feedback";
import { Card, SectionHeader } from "../../components/layout/Page";
import { formatReportFigure } from "../admin-reports/report-format";

/*
 * Live operating figures across every merchant, from the platform reports endpoint (which takes
 * no merchant to mean "all of them"). The summary items are whatever the backend reports for
 * each type, so a new figure added server-side shows up here without a release.
 */

type Period = "today" | "7d" | "month";

const PERIODS: Array<{ value: Period; label: string; reportRange: string }> = [
  { value: "today", label: "Today", reportRange: "today" },
  { value: "7d", label: "Last 7 days", reportRange: "7d" },
  { value: "month", label: "This month", reportRange: "month" }
];

const PANELS: Array<{ type: ReportType; title: string; icon: IconName; tone: string }> = [
  { type: "DAILY_DELIVERY", title: "Deliveries", icon: "truck", tone: "blue" },
  { type: "PAYMENT_COLLECTION", title: "Collections", icon: "wallet", tone: "green" },
  { type: "PENDING_PICKUP", title: "Empties pending", icon: "refresh", tone: "amber" },
  { type: "EXPENSE", title: "Expenses", icon: "fileText", tone: "violet" }
];

function iso(date: Date) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function rangeFor(period: Period) {
  const today = new Date();
  const from =
    period === "today"
      ? iso(today)
      : period === "month"
        ? iso(new Date(today.getFullYear(), today.getMonth(), 1))
        : iso(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 6));
  return { from: `${from}T00:00:00+05:30`, to: `${iso(today)}T23:59:59+05:30` };
}

function ReportPanel({ type, title, icon, tone, period }: (typeof PANELS)[number] & { period: Period }) {
  const params = { type, ...rangeFor(period) };
  const query = useQuery({
    queryKey: queryKeys.reports.detail(params),
    queryFn: ({ signal }) => getReport(params, signal),
    staleTime: 60_000,
    refetchInterval: period === "today" ? 120_000 : false,
    retry: false
  });
  const [headline, ...rest] = query.data?.summary ?? [];
  const reportRange = PERIODS.find((p) => p.value === period)?.reportRange ?? "";

  return (
    <Card className="stat-card" bodyless>
      <div style={{ padding: "var(--space-4)", display: "flex", flexDirection: "column", gap: 10, height: "100%" }}>
        <div className="stat-card__top">
          <span className="stat-card__label">{title}</span>
          <span className={`stat-card__icon tone-${tone}`} aria-hidden="true">
            <Icon name={icon} size={18} />
          </span>
        </div>
        {query.isLoading ? (
          <>
            <Skeleton width={90} height={28} />
            <Skeleton width="70%" height={12} />
          </>
        ) : query.error ? (
          <InlineError error={query.error} onRetry={() => void query.refetch()} />
        ) : headline ? (
          <>
            <span className="stat-card__value">{formatReportFigure(headline.label, headline.value)}</span>
            <span className="stat-card__hint">{headline.label}</span>
            {rest.length ? (
              <dl className="stack" style={{ gap: 4, margin: 0 }}>
                {rest.slice(0, 3).map((item) => (
                  <div key={item.label} className="row-between" style={{ gap: 8 }}>
                    <dt className="text-muted text-small">{item.label}</dt>
                    <dd className="text-small" style={{ margin: 0, fontWeight: 600 }}>
                      {formatReportFigure(item.label, item.value)}
                    </dd>
                  </div>
                ))}
              </dl>
            ) : null}
          </>
        ) : (
          <span className="text-muted text-small">Nothing recorded in this period.</span>
        )}
        <Link
          className="stat-card__link"
          style={{ marginTop: "auto" }}
          to={`/admin/reports?type=${type}${reportRange ? `&range=${reportRange}` : ""}`}
        >
          Full report <Icon name="arrowRight" size={14} />
        </Link>
      </div>
    </Card>
  );
}

export function NetworkOperations() {
  const [period, setPeriod] = useState<Period>("today");
  return (
    <section className="stack" aria-labelledby="network-ops-heading">
      <SectionHeader
        id="network-ops-heading"
        title="Network Operations"
        description="Deliveries, money collected, empties and spend across every merchant."
        actions={
          <div className="status-tabs" role="tablist" aria-label="Operations period" style={{ border: 0 }}>
            {PERIODS.map((item) => (
              <button key={item.value} type="button" role="tab" aria-selected={period === item.value} onClick={() => setPeriod(item.value)}>
                {item.label}
              </button>
            ))}
          </div>
        }
      />
      <div className="kpi-grid">
        {PANELS.map((panel) => (
          <ReportPanel key={panel.type} {...panel} period={period} />
        ))}
      </div>
    </section>
  );
}
