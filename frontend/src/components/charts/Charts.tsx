import type { ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps
} from "recharts";

import { formatNumber } from "../../utils/format";

/*
 * Chart primitives for the admin panel.
 *
 * Every chart lives on the same deep-blue analytics panel, in both light and dark themes, so
 * the analytics band reads as one surface rather than a grid of pale boxes. Colours come from
 * the `--panel-*` tokens; a chart never hard-codes a hex value, and nothing here needs to know
 * which theme is active.
 *
 * Series identity uses a fixed order (never cycled); state (approved/pending/failed) uses the
 * status palette and always ships with a text label beside the swatch.
 */

/** Categorical series, in fixed order, stepped for the panel surface. */
export const SERIES = [
  "var(--panel-series-1)",
  "var(--panel-series-2)",
  "var(--panel-series-3)",
  "var(--panel-series-4)"
] as const;

/** Reserved for state, never for "series 4". */
export const STATUS_COLORS = {
  success: "var(--panel-success)",
  warning: "var(--panel-warning)",
  danger: "var(--panel-danger)",
  neutral: "var(--panel-neutral)",
  info: "var(--panel-series-1)"
} as const;

/**
 * A first guess at the plot size, used for the render before the container is measured.
 * Without it the chart draws once at 0×0 — which paints nothing, warns on every mount, and in
 * a layout-less environment (jsdom) never stops warning.
 */
const INITIAL_SIZE = { width: 600, height: 220 };

const AXIS_TICK = { fill: "var(--panel-axis)", fontSize: 11 };

/* ------------------------------------------------------------------------------------------ */

type ChartCardProps = {
  title: ReactNode;
  subtitle?: ReactNode;
  /** Small uppercase label above the title. */
  eyebrow?: ReactNode;
  /** Controls in the header, typically a range select. */
  actions?: ReactNode;
  /** A short insight sentence under the chart. */
  footer?: ReactNode;
  /** Headline figure shown above the plot. */
  value?: ReactNode;
  trend?: ReactNode;
  children: ReactNode;
  className?: string;
};

export function ChartCard({ title, subtitle, eyebrow, actions, footer, value, trend, children, className }: ChartCardProps) {
  return (
    <section className={["chart-card", className].filter(Boolean).join(" ")}>
      <header className="chart-card__header">
        <div className="chart-card__titles">
          {eyebrow ? <p className="chart-card__eyebrow">{eyebrow}</p> : null}
          <h3 className="chart-card__title">{title}</h3>
          {subtitle ? <p className="chart-card__subtitle">{subtitle}</p> : null}
        </div>
        {actions ? <div className="chart-card__actions">{actions}</div> : null}
      </header>
      {value !== undefined ? (
        <div className="chart-card__value">
          <strong>{value}</strong>
          {trend}
        </div>
      ) : null}
      <div className="chart-card__body">{children}</div>
      {footer ? <footer className="chart-card__footer">{footer}</footer> : null}
    </section>
  );
}

/** Compact select used in chart headers ("Last 7 days"). */
export function RangeSelect<T extends string>({
  value,
  options,
  onChange,
  label
}: {
  value: T;
  options: Array<{ value: T; label: string }>;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <select className="panel-select" aria-label={label} value={value} onChange={(event) => onChange(event.target.value as T)}>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

/** Legend with a swatch per series. Text stays in ink colours; only the swatch carries hue. */
export function ChartLegend({ items }: { items: Array<{ label: string; color: string; value?: ReactNode }> }) {
  return (
    <ul className="chart-legend list-plain">
      {items.map((item) => (
        <li key={item.label}>
          <span className="chart-legend__swatch" style={{ background: item.color }} aria-hidden="true" />
          <span className="chart-legend__label">{item.label}</span>
          {item.value !== undefined ? <strong className="chart-legend__value">{item.value}</strong> : null}
        </li>
      ))}
    </ul>
  );
}

/** Screen-reader table of the plotted values, so the chart is never the only way to read them. */
function DataTableFallback({ caption, columns, rows }: { caption: string; columns: string[]; rows: Array<Array<string | number>> }) {
  return (
    <table className="sr-only">
      <caption>{caption}</caption>
      <thead>
        <tr>
          {columns.map((column) => (
            <th key={column} scope="col">
              {column}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index}>
            {row.map((cell, cellIndex) => (
              <td key={cellIndex}>{typeof cell === "number" ? formatNumber(cell) : cell}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ChartTooltip({ active, payload, label, unit }: TooltipProps<number, string> & { unit?: string }) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="chart-tooltip">
      <p className="chart-tooltip__label">{label}</p>
      <ul className="list-plain">
        {payload.map((entry) => (
          <li key={String(entry.dataKey)}>
            <span className="chart-legend__swatch" style={{ background: entry.color }} aria-hidden="true" />
            <span>{entry.name}</span>
            <strong>
              {formatNumber(entry.value as number)}
              {unit ? ` ${unit}` : ""}
            </strong>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ------------------------------------------------------------------------------------------ */

type Series<K extends string> = { key: K; label: string; color: string };

type TrendProps<T, K extends string> = {
  data: T[];
  xKey: keyof T & string;
  series: Array<Series<K>>;
  caption: string;
  height?: number;
  unit?: string;
};

/**
 * Smooth area trend with a crosshair tooltip.
 *
 * A unique gradient id per series is required because ids are global to the document: two
 * charts sharing a key would otherwise fight over the same `<linearGradient>`.
 */
export function AreaTrendChart<T extends Record<string, string | number>, K extends keyof T & string>({
  data,
  xKey,
  series,
  caption,
  height = 220,
  unit
}: TrendProps<T, K>) {
  const gradientId = (key: string) => `area-${caption.replace(/\W+/g, "-").toLowerCase()}-${key}`;
  return (
    <figure className="chart" aria-label={caption}>
      <div aria-hidden="true" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%" initialDimension={INITIAL_SIZE}>
          <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
            <defs>
              {series.map((item) => (
                <linearGradient key={item.key} id={gradientId(item.key)} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={item.color} stopOpacity={0.5} />
                  <stop offset="95%" stopColor={item.color} stopOpacity={0.02} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid vertical={false} stroke="var(--panel-grid)" strokeDasharray="3 3" />
            <XAxis dataKey={xKey} tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={16} />
            <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} allowDecimals={false} width={38} />
            <Tooltip content={<ChartTooltip unit={unit} />} cursor={{ stroke: "rgba(255,255,255,.28)", strokeWidth: 1 }} />
            {series.map((item) => (
              <Area
                key={item.key}
                type="monotone"
                dataKey={item.key}
                name={item.label}
                stroke={item.color}
                strokeWidth={3}
                fill={`url(#${gradientId(item.key)})`}
                activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--panel-solid)" }}
                dot={false}
                /* Without this a resize can leave the drawn path at its previous width. */
                isAnimationActive={false}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <DataTableFallback
        caption={caption}
        columns={[xKey, ...series.map((item) => item.label)]}
        rows={data.map((row) => [row[xKey], ...series.map((item) => row[item.key])])}
      />
    </figure>
  );
}

/** Vertical bars; several series stack, separated by a hairline in the panel colour. */
export function ColumnChart<T extends Record<string, string | number>, K extends keyof T & string>({
  data,
  xKey,
  series,
  caption,
  height = 220,
  unit,
  stacked
}: TrendProps<T, K> & { stacked?: boolean }) {
  return (
    <figure className="chart" aria-label={caption}>
      <div aria-hidden="true" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%" initialDimension={INITIAL_SIZE}>
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }} barCategoryGap="28%">
            <CartesianGrid vertical={false} stroke="var(--panel-grid)" strokeDasharray="3 3" />
            <XAxis dataKey={xKey} tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={8} />
            <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} allowDecimals={false} width={38} />
            <Tooltip content={<ChartTooltip unit={unit} />} cursor={{ fill: "rgba(255,255,255,.06)" }} />
            {series.map((item, index) => (
              <Bar
                key={item.key}
                dataKey={item.key}
                name={item.label}
                fill={item.color}
                stackId={stacked ? "stack" : undefined}
                stroke="var(--panel-solid)"
                strokeWidth={stacked ? 1 : 0}
                maxBarSize={28}
                radius={!stacked || index === series.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <DataTableFallback
        caption={caption}
        columns={[xKey, ...series.map((item) => item.label)]}
        rows={data.map((row) => [row[xKey], ...series.map((item) => row[item.key])])}
      />
    </figure>
  );
}

type Slice = { label: string; value: number; color: string };

/** Part-to-whole ring with the total in the middle and a labelled legend beside it. */
export function DonutChart({ slices, caption, centerLabel }: { slices: Slice[]; caption: string; centerLabel: string }) {
  const total = slices.reduce((sum, slice) => sum + slice.value, 0);
  return (
    <figure className="donut" aria-label={caption}>
      <div className="donut__plot" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%" initialDimension={INITIAL_SIZE}>
          <PieChart>
            <Pie
              data={slices}
              dataKey="value"
              nameKey="label"
              innerRadius="70%"
              outerRadius="100%"
              paddingAngle={2}
              stroke="var(--panel-solid)"
              strokeWidth={2}
              startAngle={90}
              endAngle={-270}
              isAnimationActive={false}
            >
              {slices.map((slice) => (
                <Cell key={slice.label} fill={slice.color} />
              ))}
            </Pie>
            <Tooltip content={<ChartTooltip />} />
          </PieChart>
        </ResponsiveContainer>
        <div className="donut__center">
          <strong>{formatNumber(total)}</strong>
          <span>{centerLabel}</span>
        </div>
      </div>
      <ChartLegend
        items={slices.map((slice) => ({
          label: slice.label,
          color: slice.color,
          value: (
            <>
              {formatNumber(slice.value)}
              <span className="chart-legend__pct">{total ? Math.round((slice.value / total) * 100) : 0}%</span>
            </>
          )
        }))}
      />
      <DataTableFallback caption={caption} columns={["Status", "Count"]} rows={slices.map((slice) => [slice.label, slice.value])} />
    </figure>
  );
}

/**
 * Horizontal bars for one measure across a few named categories. One colour for every bar -
 * the categories are nominal, so hue would only repeat what the label already says.
 */
export function BarList({
  items,
  caption,
  color = "var(--panel-series-1)",
  valueSuffix
}: {
  items: Array<{ label: string; value: number; hint?: string }>;
  caption: string;
  color?: string;
  valueSuffix?: string;
}) {
  const max = Math.max(...items.map((item) => item.value), 1);
  const total = items.reduce((sum, item) => sum + item.value, 0) || 1;
  return (
    <ul className="bar-list list-plain" aria-label={caption}>
      {items.map((item) => (
        <li key={item.label} className="bar-list__row">
          <div className="bar-list__meta">
            <span className="bar-list__label">{item.label}</span>
            <span className="bar-list__value">
              <strong>{formatNumber(item.value)}</strong>
              {valueSuffix ? ` ${valueSuffix}` : ""}
              <span className="bar-list__pct">{Math.round((item.value / total) * 100)}%</span>
            </span>
          </div>
          <span className="bar-list__track" aria-hidden="true">
            <span style={{ width: `${(item.value / max) * 100}%`, background: color }} />
          </span>
        </li>
      ))}
    </ul>
  );
}

/** One full-width bar split into status segments, with a legend. For 2-4 states of one whole. */
export function SegmentedBar({ segments, caption }: { segments: Slice[]; caption: string }) {
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);
  return (
    <figure className="segmented-bar" aria-label={caption}>
      <div className="segmented-bar__track" aria-hidden="true">
        {total === 0 ? (
          <span style={{ flex: 1, background: "var(--panel-track)" }} />
        ) : (
          segments
            .filter((segment) => segment.value > 0)
            .map((segment) => (
              <span
                key={segment.label}
                style={{ flex: segment.value, background: segment.color }}
                title={`${segment.label}: ${formatNumber(segment.value)}`}
              />
            ))
        )}
      </div>
      <ChartLegend items={segments.map((segment) => ({ label: segment.label, color: segment.color, value: formatNumber(segment.value) }))} />
    </figure>
  );
}

/** Label/value rows for figures shown beside a chart inside a panel. */
export function PanelStatList({ items }: { items: Array<{ label: string; value: ReactNode }> }) {
  return (
    <ul className="panel-stat-list list-plain">
      {items.map((item) => (
        <li key={item.label}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </li>
      ))}
    </ul>
  );
}
