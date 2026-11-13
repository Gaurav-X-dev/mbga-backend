import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../../api/client";
import { queryKeys } from "../../api/query-keys";
import { deleteCustomerBranch, getCustomer, listCustomers, type Customer } from "../../api/customers.api";
import { Button, ButtonLink } from "../../components/common/Button";
import { ConfirmationDialog } from "../../components/feedback/Dialogs";
import { ErrorState } from "../../components/feedback/Feedback";
import { Field, Input, Select } from "../../components/forms/Field";
import { Card } from "../../components/layout/Page";
import { humanize } from "../../utils/format";
import { CustomerTeamPanel } from "./CustomerTeamPanel";
import { AddCustomerDialog } from "./AddCustomerDialog";
import { EditCustomerDialog } from "./EditCustomerDialog";
import "./customer-access.css";

type Account = { id: string; name: string; code: string; mobile: string; status: string; permissions: string[] };
type Hierarchy = { brand: { id: string; name: string } | null; owner: Account | null; branches: Account[]; isOwner: boolean; accountKind: string; canCreateBranches: boolean; permissionCatalog: string[] };
type Props = { customerId: string; customerName?: string; merchantId: string; merchant: boolean; canManage: boolean; canCreate?: boolean; canDelete?: boolean };

export function CustomerAccessPanel({ customerId, customerName, merchantId, merchant, canManage, canCreate = false, canDelete = false }: Props) {
  const client = useQueryClient();
  const root = `/${merchant ? "merchant" : "admin"}/customer-access`;
  const params = merchant ? {} : { merchantId };
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [linking, setLinking] = useState(false);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState("");
  const [editing, setEditing] = useState<Customer | null>(null);
  const [deleting, setDeleting] = useState<Account | null>(null);
  const hierarchy = useQuery({
    queryKey: ["customer-access", merchantId, customerId, "hierarchy"],
    queryFn: async ({ signal }) => (await apiClient.get<Hierarchy>(`${root}/customers/${customerId}/hierarchy`, { params, signal })).data
  });
  const data = hierarchy.data;
  const accountUrl = (id: string) => `${merchant ? "/merchant/customers" : "/admin/customer-accounts"}/${id}${merchant ? "" : `?merchant=${encodeURIComponent(merchantId)}`}`;
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["customer-access"] }),
      client.invalidateQueries({ queryKey: queryKeys.customers.all })
    ]);
  };
  const link = useMutation({
    mutationFn: () => apiClient.post(`${root}/brands/${data!.brand!.id}/outlets`, { customerId: selected }, { params }),
    onSuccess: async () => { setLinking(false); setSelected(""); await refresh(); }
  });
  const loadEdit = useMutation({ mutationFn: (id: string) => getCustomer(merchantId, id), onSuccess: setEditing });
  const candidates = useQuery({
    queryKey: ["customer-access", merchantId, "candidates", search, page], enabled: linking,
    queryFn: ({ signal }) => listCustomers({ merchantId, search, limit: 20, offset: page * 20 }, signal)
  });
  if (hierarchy.isError) return <Card title="Owner & branches"><ErrorState error={hierarchy.error} onRetry={() => void hierarchy.refetch()} /></Card>;
  if (!data) return <Card title="Owner & branches"><p role="status">Loading owner and branches…</p></Card>;

  // A child shows its owner only. It has no branch list, create action or management controls.
  if (data.accountKind === "BRANCH" || (!data.isOwner && data.owner)) {
    return <Card title="Branch account"><p><strong>{customerName || "This customer"}</strong> is a branch of {data.owner ? <a href={accountUrl(data.owner.id)}>{data.owner.name}</a> : "its linked owner"}.</p>{data.owner?.code ? <p className="meta">Owner account: {data.owner.code}</p> : null}</Card>;
  }

  return <><Card title="Owner & branches">
    <p>{customerName || "This account"} can own branches. Each branch keeps its own orders, invoices and balance.</p>
    <div className="hierarchy-actions">
      <Button variant="secondary" onClick={() => setOpen(!open)}>{open ? "Hide branches" : `View branches (${data.branches.length})`}</Button>
      {canManage && canCreate && data.canCreateBranches !== false ? <Button onClick={() => setAdding(true)}>Create branch</Button> : null}
      {open && canManage && data.brand ? <Button variant="secondary" onClick={() => setLinking(!linking)}>Link existing customer</Button> : null}
    </div>
    {loadEdit.isError || link.isError ? <ErrorState error={loadEdit.error || link.error} /> : null}
    {open ? <section className="customer-hierarchy">
      {linking ? <div className="hierarchy-form">
        <Field label="Find an existing customer"><Input value={search} onChange={e => { setSearch(e.target.value); setPage(0); setSelected(""); }} /></Field>
        {candidates.isError ? <ErrorState error={candidates.error} /> : null}
        <Field label="Customer to link"><Select value={selected} placeholder="Select customer" options={(candidates.data?.items || []).filter(c => c.id !== customerId && c.accountKind !== "BRANCH" && c.accountKind !== "OWNER").map(c => ({ value: c.id, label: `${c.businessName || c.ownerName || c.code} · ${c.code}` }))} onChange={e => setSelected(e.target.value)} /></Field>
        <div className="hierarchy-actions"><Button variant="secondary" disabled={!page} onClick={() => { setPage(page - 1); setSelected(""); }}>Previous</Button><Button variant="secondary" disabled={(candidates.data?.items.length || 0) < 20} onClick={() => { setPage(page + 1); setSelected(""); }}>Next</Button><Button disabled={!selected || link.isPending} onClick={() => link.mutate()}>Link branch</Button></div>
      </div> : null}
      {data.branches.length ? <div className="hierarchy-branches">{data.branches.map(branch => <article className="hierarchy-branch" key={branch.id}>
        <h4>{branch.name}</h4><p>{branch.code} · {humanize(branch.status)}</p><p>Phone: {branch.mobile}</p><p className="meta">Branch of {customerName || data.owner?.name}</p>
        <div className="hierarchy-actions"><ButtonLink to={accountUrl(branch.id)} variant="secondary">Open branch</ButtonLink>{canManage ? <Button variant="secondary" disabled={loadEdit.isPending} onClick={() => loadEdit.mutate(branch.id)}>Edit branch</Button> : null}{canDelete ? <Button variant="danger" onClick={() => setDeleting(branch)}>Delete branch</Button> : null}</div>
      </article>)}</div> : <p>No branches yet.</p>}
    </section> : null}
    {adding ? <AddCustomerDialog open merchantId={merchantId} branchOwnerId={customerId} onClose={() => setAdding(false)} onCreated={() => { setOpen(true); void refresh(); }} /> : null}
    {editing ? <EditCustomerDialog permissionCatalog={data.permissionCatalog} customer={editing} merchantId={merchantId} branchOwnerId={customerId} onClose={() => setEditing(null)} onSaved={() => void refresh()} /> : null}
    <ConfirmationDialog open={Boolean(deleting)} title="Delete this branch?" description={`${deleting?.name || "This branch"} will be permanently deleted. Branches with transaction history cannot be deleted.`} confirmLabel="Delete branch" confirmVariant="danger" onClose={() => setDeleting(null)} onConfirm={async () => { await deleteCustomerBranch(merchantId, customerId, deleting!.id); setDeleting(null); await refresh(); }} />
  </Card><CustomerTeamPanel scope={{ownerId:customerId,merchantId,merchant}} canManage={canManage}/></>;
}
