import { useQuery } from "@tanstack/react-query";
import { Fragment, useMemo } from "react";

import { getInventory } from "../../api/inventory.api";
import { queryKeys } from "../../api/query-keys";
import { getReport } from "../../api/reports.api";
import { Button } from "../../components/common/Button";
import { Alert, EmptyState, InlineError, LoadingSkeleton } from "../../components/feedback/Feedback";
import { Card } from "../../components/layout/Page";
import { useToast } from "../../components/feedback/toast-context";
import { downloadCsv } from "../../utils/csv";
import { formatDate } from "../../utils/format";
import { cylinderLabel } from "./report-format";
import { LINES, buildRegister, istDay, orderTypes, toMovements, type Counts, type RegisterDay } from "./stock-register";

const cell = (v: number | undefined) => (v ? (v > 0 ? String(v) : `−${Math.abs(v)}`) : "—");
const signed = (v: number | undefined) => (v ? (v > 0 ? `+${v}` : `−${Math.abs(v)}`) : "—");

const th: React.CSSProperties = { textAlign: "center", whiteSpace: "nowrap" };
const num: React.CSSProperties = { textAlign: "right", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" };
const divider: React.CSSProperties = { borderLeft: "1px solid var(--border)" };

function Row({
  label,
  counts,
  types,
  strong,
  sign,
  muted
}: {
  label: string;
  counts: Counts;
  types: string[];
  strong?: boolean;
  sign?: boolean;
  muted?: boolean;
}) {
  const fmt = sign ? signed : cell;
  return (
    <tr style={strong ? { fontWeight: 700, background: "var(--surface-muted, #f8fafc)" } : undefined}>
      <th scope="row" style={{ whiteSpace: "nowrap", fontWeight: strong ? 700 : 500 }} className={muted ? "text-muted" : undefined}>
        {label}
      </th>
      {types.map((t) => (
        <Fragment key={t}>
          <td style={{ ...num, ...divider }}>{fmt(counts[t]?.f)}</td>
          <td style={num}>{fmt(counts[t]?.e)}</td>
        </Fragment>
      ))}
    </tr>
  );
}

function DayCard({ day, types, withBalances }: { day: RegisterDay; types: string[]; withBalances: boolean }) {
  const lineRows = (block: "morning" | "supply") =>
    LINES.filter((l) => l.block === block)
      // An all-zero line is noise in a register; leave it out.
      .filter((l) => types.some((t) => day.lines[l.key][t]?.f || day.lines[l.key][t]?.e))
      .map((l) => <Row key={l.key} label={l.label} counts={day.lines[l.key]} types={types} sign />);

  const section = (title: string) => (
    <tr>
      <td colSpan={types.length * 2 + 1} style={{ fontWeight: 700, textTransform: "uppercase", fontSize: "0.72rem", letterSpacing: "0.06em", color: "var(--text-muted, #6b7280)", paddingTop: 12 }}>
        {title}
      </td>
    </tr>
  );

  return (
    <Card
      title={formatDate(day.day)}
      subtitle={day.movementCount ? `${day.movementCount} movement${day.movementCount === 1 ? "" : "s"}` : "No movement"}
      headingLevel={3}
    >
      <div className="table-wrap">
        <table className="data-table" style={{ minWidth: 160 + types.length * 120 }}>
          <caption className="sr-only">Stock register for {formatDate(day.day)}</caption>
          <thead>
            <tr>
              <th rowSpan={2} style={{ verticalAlign: "bottom" }}>
                Line
              </th>
              {types.map((t) => (
                <th key={t} colSpan={2} style={{ ...th, ...divider }}>
                  {cylinderLabel(t)}
                </th>
              ))}
            </tr>
            <tr>
              {types.map((t) => (
                <Fragment key={t}>
                  <th style={{ ...th, ...divider }} title="Filled">
                    F
                  </th>
                  <th style={th} title="Empty">
                    E
                  </th>
                </Fragment>
              ))}
            </tr>
          </thead>
          <tbody>
            {section("Morning stock")}
            {withBalances ? <Row label="Opening stock" counts={day.opening} types={types} muted /> : null}
            {lineRows("morning")}
            {withBalances ? <Row label="= Morning stock" counts={day.morning} types={types} strong /> : null}
            {section("Supply")}
            {lineRows("supply")}
            {withBalances ? <Row label="= Closing stock" counts={day.closing} types={types} strong /> : null}
          </tbody>
        </table>
      </div>
      {day.notes.length ? (
        <ul className="list-plain stack" style={{ gap: 4, marginTop: "var(--space-3)" }}>
          {day.notes.map((n) => (
            <li key={n} className="text-small">
              • {n}
            </li>
          ))}
        </ul>
      ) : null}
    </Card>
  );
}

/**
 * Stock movements laid out like the godown's paper register: one card per day, a Morning
 * stock block and a Supply block, filled (F) and empty (E) columns for every cylinder type.
 */
export function StockRegister({
  rows,
  merchantId,
  periodFrom,
  periodTo,
  merchantName
}: {
  rows: Array<Record<string, unknown>>;
  merchantId: string | undefined;
  periodFrom: string;
  /** Last day of the report period (YYYY-MM-DD); quiet days are filled up to it, never past today. */
  periodTo?: string;
  merchantName?: string;
}) {
  const toast = useToast();
  const inventory = useQuery({
    queryKey: queryKeys.inventory.snapshot(merchantId ?? ""),
    queryFn: ({ signal }) => getInventory(merchantId!, signal),
    enabled: Boolean(merchantId),
    staleTime: 30_000
  });

  // Balances walk back from now, so they need every movement from the period start until now -
  // not just the period's. Today's end is "now" for this purpose.
  const now = new Date();
  const tailParams = {
    type: "STOCK_MOVEMENT" as const,
    from: periodFrom,
    to: `${istDay(now.toISOString())}T23:59:59+05:30`,
    merchantId
  };
  const tail = useQuery({
    queryKey: queryKeys.reports.detail(tailParams),
    queryFn: ({ signal }) => getReport(tailParams, signal),
    enabled: Boolean(merchantId),
    staleTime: 30_000
  });

  const shown = useMemo(() => toMovements(rows), [rows]);
  const sinceStart = useMemo(() => toMovements(tail.data?.rows ?? []), [tail.data]);

  const current: Counts | null = useMemo(() => {
    if (!inventory.data) return null;
    return Object.fromEntries(inventory.data.items.map((i) => [i.cylinderType, { f: i.filled, e: i.empty }]));
  }, [inventory.data]);

  const types = useMemo(
    () => orderTypes([...(inventory.data?.items.map((i) => i.cylinderType) ?? []), ...shown.map((m) => m.cylinderType)]),
    [inventory.data, shown]
  );

  const withBalances = Boolean(merchantId && current && tail.data);
  const today = istDay(new Date().toISOString());
  const untilDay = periodTo && periodTo < today ? periodTo : today;
  const days = useMemo(
    () => buildRegister(shown, withBalances ? sinceStart : [], withBalances ? current : null, types, untilDay),
    [shown, sinceStart, current, types, withBalances, untilDay]
  );

  function exportRegister() {
    const header = ["Date", "Line", ...types.flatMap((t) => [`${cylinderLabel(t)} F`, `${cylinderLabel(t)} E`])];
    const body: Array<Array<string | number>> = [];
    const push = (date: string, label: string, c: Counts) => body.push([date, label, ...types.flatMap((t) => [c[t]?.f ?? 0, c[t]?.e ?? 0])]);
    for (const day of [...days].reverse()) {
      const date = formatDate(day.day);
      if (withBalances) push(date, "Opening stock", day.opening);
      for (const l of LINES.filter((x) => x.block === "morning")) push(date, l.label.replace(/^[+−±]\s*/, ""), day.lines[l.key]);
      if (withBalances) push(date, "Morning stock", day.morning);
      for (const l of LINES.filter((x) => x.block === "supply")) push(date, l.label.replace(/^[+−±]\s*/, ""), day.lines[l.key]);
      if (withBalances) push(date, "Closing stock", day.closing);
      for (const note of day.notes) body.push([date, `Note: ${note}`]);
      body.push([]);
    }
    const slug = (merchantName ?? "all-merchants").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    downloadCsv(`stock-register-${slug}.csv`, header, body);
    toast.success(`Exported the register for ${days.length} day${days.length === 1 ? "" : "s"}.`);
  }

  if (!shown.length) {
    return (
      <Card>
        <EmptyState icon="box" title="No stock movements in this period" description="Refills, plant returns, deliveries and empties appear here day by day." />
      </Card>
    );
  }

  return (
    <div className="stack-lg">
      <div className="row-between" style={{ gap: 12, flexWrap: "wrap" }}>
        <div>
          {!merchantId ? (
            <Alert tone="info">
              Choose a merchant to see opening, morning and closing stock. Without one, the register shows only what moved, because
              stock is counted per godown.
            </Alert>
          ) : inventory.isLoading || tail.isLoading ? (
            <LoadingSkeleton rows={1} label="Working out balances" />
          ) : inventory.error || tail.error ? (
            <InlineError error={inventory.error ?? tail.error} title="Balances could not be worked out" onRetry={() => void (inventory.error ? inventory.refetch() : tail.refetch())} />
          ) : (
            <span className="text-muted text-small">Balances are worked back from the live stock count. F = filled, E = empty.</span>
          )}
        </div>
        <Button variant="secondary" icon="download" onClick={exportRegister}>
          Export register (CSV)
        </Button>
      </div>
      {days.map((day) => (
        <DayCard key={day.day} day={day} types={types} withBalances={withBalances} />
      ))}
    </div>
  );
}
