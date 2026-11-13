import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listCustomers } from "../../api/customers.api";
import { assignReportGroup, saveReportGroup, type CustomerReportGroup } from "../../api/receivables.api";
import { normalizeError } from "../../api/errors";
import { Button } from "../../components/common/Button";
import { Field, Input, Select } from "../../components/forms/Field";
import { Modal } from "../../components/feedback/Dialogs";
import { ErrorState } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Pagination } from "../../components/tables/DataTable";

export function CustomerReportGroups({ merchantId, groups, onClose }: {
  merchantId: string; groups: CustomerReportGroup[]; onClose: () => void;
}) {
  const toast = useToast();
  const cache = useQueryClient();
  const [editing, setEditing] = useState("");
  const [name, setName] = useState("");
  const [active, setActive] = useState(true);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string[]>([]);
  const [targetGroup, setTargetGroup] = useState("");
  const params = { merchantId, search, customerType: "ALL", accountStatus: "ALL", limit: 25, offset: (page - 1) * 25 };
  const customers = useQuery({ queryKey: ["receivable-group-customers", params], queryFn: ({ signal }) => listCustomers(params, signal) });
  const refresh = async () => {
    await Promise.all([cache.invalidateQueries({ queryKey: ["receivables"] }), cache.invalidateQueries({ queryKey: ["report-groups"] })]);
  };
  const save = useMutation({
    mutationFn: () => saveReportGroup(merchantId, { name: name.trim(), active }, editing || undefined),
    onSuccess: async () => { setName(""); setEditing(""); setActive(true); toast.success("Group saved."); await refresh(); },
    onError: (e) => toast.error(normalizeError(e).userMessage)
  });
  const assign = useMutation({
    mutationFn: () => assignReportGroup(merchantId, selected, targetGroup || null),
    onSuccess: async () => { setSelected([]); toast.success("Customer groups updated."); await refresh(); },
    onError: (e) => toast.error(normalizeError(e).userMessage)
  });
  const busy = save.isPending || assign.isPending;
  return <Modal open wide title="Customer reporting groups" description="Each customer has one reporting group. Archived groups retain their members and report history." onClose={onClose} busy={busy}>
    <div className="stack">
      <div className="row" style={{ gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
        <Field label="Edit group"><Select value={editing} placeholder="Create a group" options={groups.map(g => ({ value: g.id, label: `${g.name}${g.active ? "" : " (archived)"}` }))} onChange={e => {
          const group = groups.find(g => g.id === e.target.value); setEditing(group?.id || ""); setName(group?.name || ""); setActive(group?.active ?? true);
        }} /></Field>
        <Field label="Group name"><Input value={name} maxLength={100} onChange={e => setName(e.target.value)} /></Field>
        <label><input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} /> Active</label>
        <Button onClick={() => save.mutate()} disabled={!name.trim() || busy} loading={save.isPending}>Save group</Button>
      </div>
      <p className="text-muted">Select customers and apply a group. Choosing Ungrouped removes their current assignment.</p>
      <Field label="Find customers"><Input value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} placeholder="Name, code or mobile" /></Field>
      {customers.isError ? <ErrorState error={customers.error} onRetry={() => void customers.refetch()} /> : null}
      {customers.isLoading ? <p>Loading customers…</p> : customers.data?.items.map(c => <label key={c.id} className="row" style={{ gap: 8 }}>
        <input type="checkbox" checked={selected.includes(c.id)} disabled={busy || (!selected.includes(c.id) && selected.length >= 100)} onChange={e => setSelected(prev => e.target.checked ? [...prev, c.id] : prev.filter(id => id !== c.id))} />
        {c.businessName || c.ownerName || c.mobile} · {c.code || c.mobile}
      </label>)}
      <Pagination page={page} pageSize={25} total={customers.data?.total || 0} onPageChange={setPage} itemLabel="customers" />
      <div className="row" style={{ gap: 12, alignItems: "flex-end" }}>
        <Field label="Assign to group"><Select value={targetGroup} placeholder="Ungrouped" options={groups.filter(g => g.active).map(g => ({ value: g.id, label: g.name }))} onChange={e => setTargetGroup(e.target.value)} /></Field>
        <Button disabled={!selected.length || busy} loading={assign.isPending} onClick={() => assign.mutate()}>Apply to {selected.length} customers</Button>
      </div>
    </div>
  </Modal>;
}
