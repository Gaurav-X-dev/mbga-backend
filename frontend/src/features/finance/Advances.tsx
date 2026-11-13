import { Link } from "react-router-dom";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listCustomers } from "../../api/customers.api";
import { getAdvance, getDeposits, getLedger, createDeposit, verifyDeposit, recordRefund, type FinanceScope, type Deposit } from "../../api/finance.api";
import { normalizeError } from "../../api/errors";
import { useAuth } from "../../auth/auth-context";
import { Button } from "../../components/common/Button";
import { Field, Input, Select, Textarea } from "../../components/forms/Field";
import { Card } from "../../components/layout/Page";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert, EmptyState, ErrorState } from "../../components/feedback/Feedback";
import { DataTable, Pagination } from "../../components/tables/DataTable";
import { formatCurrency, formatDateTime, humanize } from "../../utils/format";

export function Advances({ scope }: { scope: FinanceScope }) {
  const auth = useAuth(); const cache = useQueryClient();
  const [customer, setCustomer] = useState(""); const [customerLabel, setCustomerLabel] = useState(""); const [pickerOpen, setPickerOpen] = useState(false); const [search, setSearch] = useState(""); const [customerPage, setCustomerPage] = useState(1);
  const [page, setPage] = useState(1); const [ledgerPage, setLedgerPage] = useState(1);
  const [dialog, setDialog] = useState<{ kind: "deposit" | "refund" | "verify"; key: string; deposit?: Deposit } | null>(null);
  const [amount, setAmount] = useState(""); const [mode, setMode] = useState("UPI"); const [reference, setReference] = useState(""); const [note, setNote] = useState("");
  const searchTerm = useDebouncedValue(search.trim());
  const customersParams = { merchantId: scope.merchantId || "", search: searchTerm, customerType: "ALL", accountStatus: "APPROVED", limit: 10, offset: (customerPage - 1) * 10 };
  const customers = useQuery({ queryKey: ["finance", "customers", scope, customersParams], queryFn: ({ signal }) => listCustomers(customersParams, signal), enabled: Boolean(scope.merchantId) && pickerOpen });
  const summary = useQuery({ queryKey: ["finance", "advance", scope, customer], queryFn: ({ signal }) => getAdvance(scope, customer, signal), enabled: Boolean(customer) });
  const deposits = useQuery({ queryKey: ["finance", "deposits", scope, customer, page], queryFn: ({ signal }) => getDeposits(scope, customer, page, signal) });
  const ledger = useQuery({ queryKey: ["finance", "ledger", scope, customer, ledgerPage], queryFn: ({ signal }) => getLedger(scope, customer, ledgerPage, signal), enabled: Boolean(customer) });
  const mutation = useMutation({ mutationFn: async (verified: boolean) => {
    if (!dialog) return;
    if (dialog.kind !== "verify" && (!validAmount || !validReference || !validNote)) throw new Error("Enter a valid whole-rupee amount, reference and reason.");
    if (dialog.kind === "verify" && note.trim().length < 3) throw new Error("Enter a verification reason of at least 3 characters.");
    if (dialog.kind === "verify") return verifyDeposit(scope, dialog.deposit!.id, verified, note);
    if (dialog.kind === "refund") return recordRefund(scope, { customerId: customer, amount: Number(amount), reference: reference.trim(), reason: note.trim(), idempotencyKey: dialog.key });
    return createDeposit(scope, { customerId: customer, amount: Number(amount), mode, reference: reference.trim() || undefined, notes: note.trim() || undefined, idempotencyKey: dialog.key });
  }, onSuccess: async () => { setDialog(null); await cache.invalidateQueries({ queryKey: ["finance"] }); await cache.invalidateQueries({ queryKey: ["payments"] }); } });
  const open = (kind: "deposit" | "refund" | "verify", deposit?: Deposit) => { setDialog({ kind, key: crypto.randomUUID(), deposit }); setAmount(""); setReference(""); setNote(""); mutation.reset(); };
  const amountLimit = dialog?.kind === "refund" ? summary.data?.available : summary.data?.maxDepositAmount;
  const validAmount = /^\d+$/.test(amount) && Number.isSafeInteger(Number(amount)) && Number(amount) > 0 && amountLimit !== undefined && Number(amount) <= amountLimit;
  const validReference = dialog?.kind === "verify" || (dialog?.kind === "deposit" && mode === "CASH") || reference.trim().length > 0;
  const validNote = dialog?.kind === "deposit" || note.trim().length >= 3;
  return <div className="stack">
    <Card title="Customer advance balance" subtitle="Deposits stay pending until office verification. Advance funds and outstanding invoices are separate.">
      <div className="finance-customer-selection">
        <div><span className="field__label">Customer</span><strong>{customerLabel || "No customer selected"}</strong><p className="meta">Search by name, code or mobile. Only approved customers can receive advances.</p></div>
        <Button variant="secondary" onClick={() => { setSearch(""); setCustomerPage(1); setPickerOpen(true); }}>{customer ? "Change customer" : "Choose customer"}</Button>
        {customer ? <Button variant="secondary" onClick={() => { setCustomer(""); setCustomerLabel(""); setPage(1); setLedgerPage(1); }}>Clear selection</Button> : null}
      </div>
      {pickerOpen ? <Modal open wide title="Choose customer" onClose={() => setPickerOpen(false)}>
        <div className="stack">
          <Field label="Search customers"><Input autoFocus maxLength={120} value={search} placeholder="Business name, owner, code or mobile" onChange={e => { setSearch(e.target.value); setCustomerPage(1); }} /></Field>
          <p className="meta" aria-live="polite">{customers.isFetching || search.trim() !== searchTerm ? "Searching customers…" : `${customers.data?.total || 0} matching customers`}</p>
          {customers.isError ? <ErrorState error={customers.error} onRetry={() => void customers.refetch()} /> : <div className="finance-customer-results">
            {(customers.data?.items || []).map(c => <button type="button" className="finance-customer-option" key={c.id} disabled={customers.isFetching || search.trim() !== searchTerm} onClick={() => { setCustomer(c.id); setCustomerLabel(c.businessName || c.ownerName || c.mobile); setPage(1); setLedgerPage(1); setPickerOpen(false); }}><strong>{c.businessName || c.ownerName || c.mobile}</strong><span>{c.code} · {c.mobile}</span></button>)}
            {!customers.isFetching && customers.data?.total === 0 ? <EmptyState title="No matching approved customers" description="Try another name, customer code or mobile number." /> : null}
          </div>}
          <Pagination page={customerPage} pageSize={10} total={customers.data?.total || 0} onPageChange={setCustomerPage} itemLabel="customers" />
        </div>
      </Modal> : null}
      {summary.isError ? <ErrorState error={summary.error} onRetry={() => void summary.refetch()} /> : null}
      <div className="finance-actions"><Button disabled={!auth.can("payments.collect") || !customer || !summary.data?.enabled || summary.isFetching} onClick={() => open("deposit")}>Record advance deposit</Button></div>
      {!customer ? <p className="meta">Select a customer above to record an advance received on their behalf by cash, UPI or bank transfer.</p> : null}
      {!auth.can("payments.collect") ? <p className="meta">Your role needs payment collection permission to record an advance.</p> : null}
      {customer && summary.isPending ? <p className="meta" role="status">Checking customer balance and advance settings…</p> : null}
      {customer && summary.data && !summary.data.enabled ? <Alert tone="warning">Advance deposits are disabled for this merchant. Enable customer advances in Admin App Settings before recording a deposit. {auth.channel === "admin" && auth.can("platform_settings.view") ? <Link to={`/admin/app-settings?merchant=${encodeURIComponent(scope.merchantId || "")}`}>Open App Settings</Link> : null}</Alert> : null}
      {summary.data ? <><div className="finance-stats">{[['Advance balance', summary.data.balance], ['Reserved for orders', summary.data.reserved], ['Available advance', summary.data.available]].map(([label, value]) => <div className="stat-card" key={String(label)}><span className="stat-card__label">{label}</span><strong className="stat-card__value">{formatCurrency(Number(value))}</strong></div>)}</div>
        {!summary.data.enabled ? <p className="meta">New advances are disabled. Admin can enable them in App Settings.</p> : null}
        <div className="finance-actions">{auth.can("payments.reconcile") ? <Button variant="secondary" disabled={!summary.data.available} onClick={() => open("refund")}>Record completed refund</Button> : null}</div>
      </> : null}
    </Card>
    <Card title="Advance deposits" subtitle={customer ? "Selected customer" : "All customers of the selected merchant"}><DataTable caption="Advance deposits" rows={deposits.data?.items} getRowKey={r => r.id} isLoading={deposits.isLoading} error={deposits.error} onRetry={() => void deposits.refetch()} empty={<EmptyState title="No deposits" />}
      columns={[{ key: "customerId", header: "Customer", render: r => r.customerName || r.customerId }, { key: "reference", header: "Receipt / reference", primary: true, render: r => r.reference || r.id }, { key: "amount", header: "Amount", render: r => formatCurrency(r.amount) }, { key: "mode", header: "Mode", render: r => r.mode }, { key: "status", header: "Status", render: r => humanize(r.status) }, { key: "createdAt", header: "Recorded", render: r => formatDateTime(r.createdAt) }, { key: "action", header: "Verification", render: r => r.status === "PENDING" && auth.can("payments.reconcile") ? <Button size="sm" onClick={() => open("verify", r)}>Verify receipt</Button> : "—" }]}
      footer={<Pagination page={page} pageSize={25} total={deposits.data?.total || 0} onPageChange={setPage} itemLabel="deposits" />} /></Card>
    {customer ? <Card title="Advance ledger"><DataTable caption="Advance ledger" rows={ledger.data?.items} getRowKey={r => r.id} isLoading={ledger.isLoading} error={ledger.error} onRetry={() => void ledger.refetch()} empty={<EmptyState title="No advance movements" />}
      columns={[{ key: "kind", header: "Movement", primary: true, render: r => humanize(r.kind) }, { key: "amount", header: "Amount", render: r => formatCurrency(r.amount) }, { key: "balanceAfter", header: "Balance after", render: r => formatCurrency(r.balanceAfter) }, { key: "reference", header: "Reference", render: r => r.reference || "—" }, { key: "createdAt", header: "Recorded", render: r => formatDateTime(r.createdAt) }]}
      footer={<Pagination page={ledgerPage} pageSize={25} total={ledger.data?.total || 0} onPageChange={setLedgerPage} itemLabel="entries" />} /></Card> : null}
    {dialog ? <Modal open title={dialog.kind === "verify" ? "Verify advance receipt" : dialog.kind === "refund" ? "Record completed refund" : "Record advance deposit"} onClose={() => setDialog(null)} busy={mutation.isPending}>
      <form className="stack" onSubmit={e => { e.preventDefault(); mutation.mutate(true); }}>
        {dialog.kind === "verify" ? <p>Confirm {formatCurrency(dialog.deposit!.amount)} for {dialog.deposit!.customerName || dialog.deposit!.customerId} was actually received. A reference or screenshot alone does not confirm payment.</p> : <>
          <Field label="Amount (₹)" hint={amountLimit !== undefined ? `Enter whole rupees, up to ${formatCurrency(amountLimit)}.` : undefined} error={amount && !validAmount ? "Enter a positive whole-rupee amount within the available limit." : undefined}><Input type="number" min={1} step={1} max={dialog.kind === "refund" ? summary.data?.available : summary.data?.maxDepositAmount} value={amount} required onChange={e => setAmount(e.target.value)} /></Field>
          {dialog.kind === "deposit" ? <Field label="Payment mode"><Select value={mode} options={[{ value: "UPI", label: "UPI" }, { value: "NEFT", label: "Bank transfer" }, { value: "CASH", label: "Office cash" }]} onChange={e => setMode(e.target.value)} /></Field> : <p className="meta">This records money already returned to the customer. It does not initiate a bank transfer. Reserved funds cannot be refunded.</p>}
          <Field label="Transaction / refund reference"><Input maxLength={100} value={reference} required={dialog.kind === "refund" || mode !== "CASH"} onChange={e => setReference(e.target.value)} /></Field>
        </>}
        <Field label={dialog.kind === "deposit" ? "Notes" : "Verification / refund reason"}><Textarea maxLength={2000} minLength={dialog.kind === "deposit" ? undefined : 3} required={dialog.kind !== "deposit"} value={note} onChange={e => setNote(e.target.value)} /></Field>
        {mutation.isError ? <Alert tone="error">{normalizeError(mutation.error).userMessage}</Alert> : null}
        <div className="finance-actions"><Button type="submit" disabled={!validNote || !validReference || (dialog.kind !== "verify" && !validAmount)} loading={mutation.isPending}>{dialog.kind === "verify" ? "Confirm received & credit advance" : dialog.kind === "refund" ? "Confirm refund recorded" : "Submit for verification"}</Button>{dialog.kind === "verify" ? <Button variant="danger" disabled={note.trim().length < 3 || mutation.isPending} onClick={() => mutation.mutate(false)}>Reject receipt</Button> : null}</div>
      </form>
    </Modal> : null}
  </div>;
}
