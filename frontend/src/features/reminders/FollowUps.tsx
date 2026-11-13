import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listReminders, updateReminder, markPricingReviewed, type ReminderScope, type FollowUp } from "../../api/reminders.api";
import { normalizeError } from "../../api/errors";
import { useAuth } from "../../auth/auth-context";
import { Button } from "../../components/common/Button";
import { Field, Input, Select, Textarea } from "../../components/forms/Field";
import { Card } from "../../components/layout/Page";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert, EmptyState } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { DataTable, Pagination, type Column } from "../../components/tables/DataTable";
import { formatDateTime, humanize } from "../../utils/format";

export function FollowUps({ scope }: { scope: ReminderScope }) {
  const auth = useAuth();
  const toast = useToast();
  const client = useQueryClient();
  const [page, setPage] = useState(1);
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("OPEN");
  const [selected, setSelected] = useState<{ row: FollowUp } | null>(null);
  const [note, setNote] = useState("");
  const [snooze, setSnooze] = useState("");
  const filters = { kind: kind || undefined, status: status || undefined, limit: 25, offset: (page - 1) * 25 };
  const query = useQuery({ queryKey: ["automated-follow-ups", scope, filters], queryFn: ({ signal }) => listReminders(scope, filters, signal) });
  const mutation = useMutation({
    mutationFn: async (action: string) => {
      if (!selected) return;
      const row = selected.row;
      if (action === "REVIEW") return markPricingReviewed(scope, String(row.context.month), note || undefined);
      return updateReminder(scope, row.id, { status: action, snoozeHours: action === "SNOOZED" ? Number(snooze) : undefined, note: note || undefined });
    },
    onSuccess: async () => { setSelected(null); await client.invalidateQueries({ queryKey: ["automated-follow-ups"] }); toast.success("Follow-up updated."); }
  });
  const open = (row: FollowUp) => { setSelected({ row }); setNote(""); setSnooze(""); mutation.reset(); };
  const columns: Column<FollowUp>[] = [
    { key: "subject", header: "Customer / pricing period", primary: true, render: row => <Button variant="link" onClick={e => { e.stopPropagation(); open(row); }}>{row.subject}</Button> },
    { key: "kind", header: "Reminder", render: row => humanize(row.kind) },
    { key: "status", header: "Status", render: row => humanize(row.status) },
    { key: "reason", header: "Reason", render: row => row.reason || String(row.context.reason || "—") },
    { key: "reminderCount", header: "Reminders issued", align: "right", render: row => row.reminderCount },
    { key: "nextDueAt", header: "Next eligible", render: row => row.nextDueAt ? formatDateTime(row.nextDueAt) : "—" }
  ];
  const row = selected?.row;
  const canAct = row && auth.can(row.kind === "PRICING" ? "pricing.manage" : "customers.update");
  return <Card title="Reminder history & merchant follow-ups" subtitle="Acknowledging stops repeats. Snoozing postpones them. New qualifying activity resolves the current episode.">
    <div className="automation-toolbar">
      <Field label="Reminder type"><Select value={kind} placeholder="All types" options={["PROXIMITY", "INACTIVE", "PRICING"].map(value => ({ value, label: humanize(value) }))} onChange={e => { setKind(e.target.value); setPage(1); }} /></Field>
      <Field label="Follow-up status"><Select value={status} placeholder="All statuses" options={["OPEN", "ACKNOWLEDGED", "SNOOZED", "RESOLVED"].map(value => ({ value, label: humanize(value) }))} onChange={e => { setStatus(e.target.value); setPage(1); }} /></Field>
      <Button variant="secondary" onClick={() => void query.refetch()} disabled={query.isFetching}>Refresh follow-ups</Button>
    </div>
    <DataTable caption="Automated follow-ups" columns={columns} rows={query.data?.items} getRowKey={r => r.id} onRowClick={open} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()}
      empty={<EmptyState title="No matching follow-ups" description="Enabled rules create follow-ups when their conditions are met." />} footer={<Pagination page={page} pageSize={25} total={query.data?.total || 0} onPageChange={setPage} itemLabel="follow-ups" />} />
    {row ? <Modal open wide title={row.subject} description={String(row.context.reason || row.reason || "")} onClose={() => setSelected(null)} busy={mutation.isPending}>
      <div className="stack">
        <p className="meta">{humanize(row.kind)} · {humanize(row.status)} · {row.reminderCount} reminders issued{row.context.site_name ? ` · ${String(row.context.site_name)}` : ""}</p>
        {row.kind === "PROXIMITY" ? <p>{String(row.context.distance_km)} km straight-line distance at evaluation time.</p> : null}
        <Field label="Follow-up notes"><Textarea maxLength={1000} value={note} onChange={e => setNote(e.target.value)} /></Field>
        {canAct && row.kind !== "PROXIMITY" && row.status !== "RESOLVED" ? <>
          <div className="automation-toolbar"><Button disabled={mutation.isPending} onClick={() => mutation.mutate("ACKNOWLEDGED")}>Acknowledge</Button><Button variant="secondary" disabled={mutation.isPending} onClick={() => mutation.mutate("RESOLVED")}>Resolve follow-up</Button></div>
          <div className="automation-toolbar"><Field label="Snooze (hours)"><Input type="number" min={1} step={1} value={snooze} onChange={e => setSnooze(e.target.value)} /></Field><Button variant="secondary" disabled={mutation.isPending || !Number.isInteger(Number(snooze)) || Number(snooze) < 1} onClick={() => mutation.mutate("SNOOZED")}>Snooze</Button></div>
          {row.kind === "PRICING" ? <><Link to={scope.merchant ? "/merchant/pricing" : `/admin/pricing?merchant=${encodeURIComponent(row.merchantId)}`}>Open pricing settings</Link>{row.context.trigger === "REVIEW" ? <Button variant="secondary" disabled={mutation.isPending} onClick={() => mutation.mutate("REVIEW")}>Mark pricing reviewed — no change needed</Button> : <p className="meta">Missing-rate reminders clear when the required rates exist; marking a review does not clear missing rates.</p>}</> : null}
        </> : null}
        {mutation.isError ? <Alert tone="error">{normalizeError(mutation.error).userMessage}</Alert> : null}
      </div>
    </Modal> : null}
  </Card>;
}
