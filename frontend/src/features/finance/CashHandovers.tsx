import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getCash, getHandovers, submitHandover, verifyHandover, type FinanceScope, type CashCollection, type Handover } from "../../api/finance.api";
import { normalizeError } from "../../api/errors";
import { useAuth } from "../../auth/auth-context";
import { Button } from "../../components/common/Button";
import { Field, Input, Select, Textarea } from "../../components/forms/Field";
import { Card } from "../../components/layout/Page";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert, EmptyState } from "../../components/feedback/Feedback";
import { DataTable, Pagination } from "../../components/tables/DataTable";
import { formatCurrency, formatDateTime, humanize, todayInputValue } from "../../utils/format";

export function CashHandovers({ scope }: { scope: FinanceScope }) {
  const auth = useAuth(); const cache = useQueryClient();
  const [filters, setFilters] = useState({ driverId: "", vehicle: "", invoice: "", dateFrom: "", dateTo: "" });
  const [page, setPage] = useState(1); const [batchPage, setBatchPage] = useState(1);
  const [selected, setSelected] = useState<Record<string, CashCollection>>({});
  const [dialog, setDialog] = useState<{ kind: "submit" | "verify"; key: string; row?: Handover } | null>(null);
  const [received, setReceived] = useState(""); const [note, setNote] = useState("");
  const validDates = !filters.dateFrom || !filters.dateTo || filters.dateFrom <= filters.dateTo;
  const params = { ...filters, driverId: filters.driverId || undefined, vehicle: filters.vehicle || undefined, invoice: filters.invoice || undefined, dateFrom: filters.dateFrom || undefined, dateTo: filters.dateTo || undefined, limit: 50, offset: (page - 1) * 50 };
  const collections = useQuery({ queryKey: ["finance", "cash", scope, params], queryFn: ({ signal }) => getCash(scope, params, signal), enabled: validDates });
  const batches = useQuery({ queryKey: ["finance", "handovers", scope, filters.driverId, batchPage], queryFn: ({ signal }) => getHandovers(scope, filters.driverId, batchPage, signal) });
  const selection = Object.values(selected); const selectedDriver = selection[0]?.driverId;
  const expected = selection.reduce((total, row) => total + row.remaining, 0);
  const mutation = useMutation({ mutationFn: async (reject: boolean) => {
    if (!dialog) return;
    if (dialog.kind === "verify" && (note.trim().length < 3 || (!reject && (!/^\d+$/.test(received) || !Number.isSafeInteger(Number(received)) || Number(received) > 100000000)))) throw new Error("Enter a whole-rupee cash amount and a verification reason.");
    return dialog.kind === "submit" ? submitHandover(scope, { driverId: selectedDriver, paymentIds: selection.map(r => r.id), idempotencyKey: dialog.key, notes: note.trim() || undefined })
      : verifyHandover(scope, dialog.row!.id, reject ? 0 : Number(received), note.trim(), reject);
  }, onSuccess: async () => { setDialog(null); setSelected({}); await cache.invalidateQueries({ queryKey: ["finance"] }); } });
  const open = (kind: "submit" | "verify", row?: Handover) => { setDialog({ kind, row, key: crypto.randomUUID() }); setNote(""); setReceived(""); mutation.reset(); };
  const filter = (key: keyof typeof filters, value: string) => { setFilters(old => ({ ...old, [key]: value })); setPage(1); setBatchPage(1); setSelected({}); };
  return <div className="stack">
    <Alert tone="info">Step 1: Select receipts not yet submitted and create a handover. Step 2: An authorized office user counts the cash and selects “Verify cash” in the handover table below. Receipts awaiting verification cannot be selected again.</Alert>
    <Card title="1. Cash collected by drivers" subtitle="These are customer payments already collected by drivers. Office cash receipt is tracked separately from customer invoice settlement.">
      <div className="finance-grid">
        <Field label="Driver"><Select value={filters.driverId} placeholder="All drivers" options={(collections.data?.drivers || []).map(driver => ({ value: driver.id, label: driver.name }))} onChange={e => filter("driverId", e.target.value)} /></Field>
        <Field label="Vehicle"><Input value={filters.vehicle} maxLength={50} placeholder="Vehicle number" onChange={e => filter("vehicle", e.target.value)} /></Field>
        <Field label="Invoice"><Input value={filters.invoice} maxLength={40} placeholder="Invoice number" onChange={e => filter("invoice", e.target.value)} /></Field>
        <Field label="Collected from"><Input type="date" max={todayInputValue()} value={filters.dateFrom} onChange={e => filter("dateFrom", e.target.value)} /></Field>
        <Field label="Collected to" error={validDates ? undefined : "Must be on or after the start date."}><Input type="date" max={todayInputValue()} value={filters.dateTo} onChange={e => filter("dateTo", e.target.value)} /></Field>
      </div>
      <p className="meta">{collections.data?.coverage}</p>
      <div className="finance-actions"><strong>Cash in driver custody: {formatCurrency(collections.data?.cashInCustody || 0)}</strong><span>Selected: {selection.length} receipts · {formatCurrency(expected)}</span>{auth.can("payments.collect") ? <Button disabled={!selection.length || !validDates || collections.isFetching} onClick={() => open("submit")}>Submit cash handover</Button> : null}<Button variant="secondary" onClick={() => { setFilters({ driverId: "", vehicle: "", invoice: "", dateFrom: "", dateTo: "" }); setPage(1); setSelected({}); }}>Reset filters</Button></div>
      <DataTable caption="Driver cash collections" rows={collections.data?.items} getRowKey={r => r.id} isLoading={collections.isLoading} error={collections.error} onRetry={() => void collections.refetch()} empty={<EmptyState title="No matching cash collections" />}
        columns={[{ key: "select", header: "Select / status", render: r => r.submittedAmount > 0 ? <span className="finance-pending-receipt">Awaiting office verification</span> : <input type="checkbox" title={!auth.can("payments.collect") ? "Payment collection permission required" : selectedDriver && selectedDriver !== r.driverId ? "Select receipts from one driver at a time" : "Select for a new handover"} aria-label={`Select ${r.invoice} receipt ${r.id}`} checked={Boolean(selected[r.id])} disabled={!auth.can("payments.collect") || r.submittedAmount > 0 || Boolean(selectedDriver && selectedDriver !== r.driverId) || (!selected[r.id] && selection.length >= 200)} onChange={e => { const checked = e.target.checked; setSelected(old => { const next = { ...old }; if (checked) next[r.id] = r; else delete next[r.id]; return next; }); }} /> }, { key: "invoice", header: "Invoice", primary: true, render: r => r.invoice }, { key: "driver", header: "Driver", render: r => r.driverName }, { key: "vehicle", header: "Vehicle", render: r => r.vehicle }, { key: "remaining", header: "Cash to hand over", render: r => formatCurrency(r.remaining) }, { key: "submittedAmount", header: "Submitted for checking", render: r => formatCurrency(r.submittedAmount) }, { key: "collectedAt", header: "Collected", render: r => formatDateTime(r.collectedAt) }]}
        footer={<Pagination page={page} pageSize={50} total={collections.data?.total || 0} onPageChange={setPage} itemLabel="collections" />} />
    </Card>
    <Card title="2. Office cash verification" subtitle="For a submitted handover, click Verify cash. Count the physical cash, enter the amount and confirm. Do not submit the same receipts again."><DataTable caption="Cash handovers" rows={batches.data?.items} getRowKey={r => r.id} isLoading={batches.isLoading} error={batches.error} onRetry={() => void batches.refetch()} empty={<EmptyState title="No handovers yet" />}
      columns={[{ key: "id", header: "Handover", primary: true, render: r => <Button variant="link" onClick={() => open("verify", r)}>{r.id.slice(0, 8)}</Button> }, { key: "driver", header: "Driver", render: r => r.items[0]?.driverName || r.driverId }, { key: "expectedAmount", header: "Expected cash", render: r => formatCurrency(r.expectedAmount) }, { key: "receivedAmount", header: "Office received", render: r => r.receivedAmount == null ? "—" : formatCurrency(r.receivedAmount) }, { key: "difference", header: "Difference", render: r => r.difference == null ? "—" : formatCurrency(r.difference) }, { key: "status", header: "Status", render: r => r.status === "SUBMITTED" ? "Awaiting office verification" : humanize(r.status) }, { key: "action", header: "Action", render: r => <Button variant="secondary" size="sm" onClick={() => open("verify", r)}>{r.status === "SUBMITTED" && auth.can("payments.reconcile") && !r.verificationBlockedReason ? "Verify cash" : "View details"}</Button> }]}
      footer={<Pagination page={batchPage} pageSize={25} total={batches.data?.total || 0} onPageChange={setBatchPage} itemLabel="handovers" />} /></Card>
    {dialog ? <Modal open wide title={dialog.kind === "submit" ? "Submit selected cash receipts" : "Office cash verification"} onClose={() => setDialog(null)} busy={mutation.isPending}>
      <form className="stack" onSubmit={e => { e.preventDefault(); mutation.mutate(false); }}>
        {dialog.kind === "verify" && dialog.row!.verificationBlockedReason ? <Alert tone="warning">{dialog.row!.verificationBlockedReason}</Alert> : null}
        <p><strong>Expected cash: {formatCurrency(dialog.kind === "submit" ? expected : dialog.row!.expectedAmount)}</strong></p>
        {dialog.kind === "submit" ? <p>{selection.length} receipts from {selection[0]?.driverName}. The office must count and verify the physical cash.</p> : <>
          <div className="table-wrap"><table className="data-table"><thead><tr><th>Invoice</th><th>Vehicle</th><th>Expected cash</th><th>Received cash</th></tr></thead><tbody>{dialog.row!.items.map((r, i) => <tr key={i}><td>{r.invoice}</td><td>{r.vehicle}</td><td>{formatCurrency(r.expectedAmount)}</td><td>{formatCurrency(r.receivedAmount)}</td></tr>)}</tbody></table></div>
          {dialog.row!.status === "SUBMITTED" && auth.can("payments.reconcile") && !dialog.row!.verificationBlockedReason ? <><Field label="Cash physically received (₹)"><Input type="number" min={0} max={100000000} step={1} required value={received} onChange={e => setReceived(e.target.value)} /></Field><p className="meta">Difference: {received ? formatCurrency(Number(received) - dialog.row!.expectedAmount) : "Enter counted cash first"}. Short cash remains in driver custody. Excess cash is recorded separately and is not credited to a customer. Receipt allocation follows collection date.</p></> : <p>{humanize(dialog.row!.status)} · {dialog.row!.verificationNotes}</p>}
        </>}
        {dialog.kind === "submit" || (dialog.row!.status === "SUBMITTED" && auth.can("payments.reconcile") && !dialog.row!.verificationBlockedReason) ? <Field label={dialog.kind === "submit" ? "Handover notes" : "Count verification / difference explanation"}><Textarea value={note} required={dialog.kind === "verify"} minLength={dialog.kind === "verify" ? 3 : undefined} maxLength={2000} onChange={e => setNote(e.target.value)} /></Field> : null}
        {mutation.isError ? <Alert tone="error">{normalizeError(mutation.error).userMessage}</Alert> : null}
        {dialog.kind === "submit" ? <Button type="submit" loading={mutation.isPending}>Confirm handover submission</Button> : dialog.row!.status === "SUBMITTED" && auth.can("payments.reconcile") && !dialog.row!.verificationBlockedReason ? <div className="finance-actions"><Button type="submit" disabled={!/^\d+$/.test(received) || !Number.isSafeInteger(Number(received)) || Number(received) > 100000000 || note.trim().length < 3} loading={mutation.isPending}>Verify cash received</Button><Button variant="danger" disabled={note.trim().length < 3 || mutation.isPending} onClick={() => mutation.mutate(true)}>Reject submission — no cash received</Button></div> : null}
      </form>
    </Modal> : null}
  </div>;
}
