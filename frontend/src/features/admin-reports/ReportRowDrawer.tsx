import { Badge } from "../../components/common/StatusBadge";
import { Drawer, DrawerSection } from "../../components/feedback/Dialogs";
import { formatDateTime, formatNumber, humanize } from "../../utils/format";
import type { Tone } from "../../utils/labels";
import { cylinderLabel, formatReportFigure } from "./report-format";

/** The `_details` block a report row may carry: everything the drill-down needs, prepared server-side. */
export type ReportRowDetails = {
  id?: string;
  title?: string;
  subtitle?: string | null;
  statusBadge?: { label: string; color?: string } | null;
  fields?: Array<{ label: string; value: unknown; highlight?: boolean }>;
  breakdown?: Array<{ title: string; quantity?: number | null; amount?: number | null; subtitle?: string | null }>;
  notes?: string | null;
  auditTrail?: Array<{ action: string; timestamp?: string | null; user?: string | null }>;
};

const BADGE_TONE: Record<string, Tone> = { success: "success", danger: "danger", error: "danger", warning: "warning", info: "info", neutral: "neutral" };

function fieldValue(label: string, value: unknown) {
  if (value === null || value === undefined || value === "") return <span className="text-muted">—</span>;
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) return formatDateTime(value);
  if (typeof value === "number") return formatReportFigure(label, value);
  return String(value);
}

export function ReportRowDrawer({ details, onClose }: { details: ReportRowDetails; onClose: () => void }) {
  const badge = details.statusBadge;
  const breakdown = (details.breakdown ?? []).filter((line) => (line.quantity ?? 0) > 0 || (line.amount ?? 0) > 0);
  return (
    <Drawer
      open
      size="lg"
      title={details.title ?? "Record"}
      subtitle={details.subtitle ?? undefined}
      meta={badge ? <Badge tone={BADGE_TONE[badge.color ?? ""] ?? "neutral"}>{humanize(badge.label)}</Badge> : undefined}
      onClose={onClose}
    >
      {details.fields?.length ? (
        <DrawerSection title="Details">
          <dl className="details">
            {details.fields.map((field) => (
              <div key={field.label} className="details__item">
                <dt className="details__label">{field.label}</dt>
                <dd className="details__value" style={field.highlight ? { fontWeight: 700 } : undefined}>
                  {fieldValue(field.label, field.value)}
                </dd>
              </div>
            ))}
          </dl>
        </DrawerSection>
      ) : null}

      {breakdown.length ? (
        <DrawerSection title="Breakdown">
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Item</th>
                  <th style={{ textAlign: "right" }}>Qty</th>
                  {breakdown.some((l) => l.amount != null) ? <th style={{ textAlign: "right" }}>Amount</th> : null}
                </tr>
              </thead>
              <tbody>
                {breakdown.map((line, index) => (
                  <tr key={`${line.title}-${index}`}>
                    <td>
                      <div className="cell-stack">
                        <span>{cylinderLabel(line.title)}</span>
                        {line.subtitle ? <small>{line.subtitle}</small> : null}
                      </div>
                    </td>
                    <td style={{ textAlign: "right" }}>{line.quantity != null ? formatNumber(line.quantity) : "—"}</td>
                    {breakdown.some((l) => l.amount != null) ? (
                      <td style={{ textAlign: "right" }}>{line.amount != null ? formatReportFigure("amount", line.amount) : "—"}</td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </DrawerSection>
      ) : null}

      {details.notes ? (
        <DrawerSection title="Notes">
          <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{details.notes}</p>
        </DrawerSection>
      ) : null}

      {details.auditTrail?.length ? (
        <DrawerSection title="History">
          <ol className="timeline">
            {details.auditTrail.map((entry, index) => (
              <li key={`${entry.timestamp}-${index}`}>
                <span>{entry.action.replace(/\b([A-Z]+(?:_[A-Z]+)+|[A-Z]{4,})\b/g, (code) => humanize(code))}</span>
                <div className="text-muted text-small">
                  {entry.timestamp ? formatDateTime(entry.timestamp) : null}
                  {entry.user ? (
                    <>
                      {" · "}
                      <span style={{ display: "inline-block", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", verticalAlign: "bottom" }} title={entry.user}>
                        {entry.user}
                      </span>
                    </>
                  ) : null}
                </div>
              </li>
            ))}
          </ol>
        </DrawerSection>
      ) : null}
    </Drawer>
  );
}
