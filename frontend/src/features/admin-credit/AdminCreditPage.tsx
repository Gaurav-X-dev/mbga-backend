import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getCreditSettings,
  listCreditCustomers,
  updateCreditSettings,
  updateCustomerCredit,
  type CreditCustomer,
  type CreditSettings
} from "../../api/credit.api";
import { Button } from "../../components/common/Button";
import { Card, PageHeader } from "../../components/layout/Page";
import { formatCurrency } from "../../utils/format";

const settingsKey = ["admin", "credit", "settings"] as const;
const customersKey = ["admin", "credit", "customers"] as const;

function CreditCustomerRow({ customer }: { customer: CreditCustomer }) {
  const queryClient = useQueryClient();
  const [enabled, setEnabled] = useState(customer.creditEnabled);
  const [limit, setLimit] = useState(customer.creditLimit);
  const [days, setDays] = useState(customer.creditDays?.toString() ?? "");
  const mutation = useMutation({
    mutationFn: () =>
      updateCustomerCredit(customer.customerId, {
        creditEnabled: enabled,
        creditLimit: Number(limit),
        creditDays: days ? Number(days) : null,
        reason: "Updated from Admin Credit Control"
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: customersKey })
  });
  return (
    <tr>
      <td><strong>{customer.customerName || "Unnamed customer"}</strong><br /><small>{customer.customerId}</small></td>
      <td><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} aria-label="Credit enabled" /></td>
      <td><input type="number" min={0} value={limit} onChange={(event) => setLimit(Number(event.target.value))} style={{ width: 120 }} /></td>
      <td><input type="number" min={1} max={365} value={days} onChange={(event) => setDays(event.target.value)} placeholder="Optional" style={{ width: 90 }} /></td>
      <td>{formatCurrency(customer.usedCredit)}</td>
      <td>{formatCurrency(customer.availableCredit)}</td>
      <td>{customer.exceeded ? "Exceeded" : "Within limit"}</td>
      <td><Button size="sm" loading={mutation.isPending} onClick={() => mutation.mutate()}>Save</Button></td>
    </tr>
  );
}

export function AdminCreditPage() {
  const queryClient = useQueryClient();
  const settingsQuery = useQuery({ queryKey: settingsKey, queryFn: getCreditSettings });
  const customersQuery = useQuery({ queryKey: customersKey, queryFn: listCreditCustomers });
  const [form, setForm] = useState<CreditSettings | null>(null);
  useEffect(() => {
    if (settingsQuery.data) setForm(settingsQuery.data);
  }, [settingsQuery.data]);
  const saveSettings = useMutation({
    mutationFn: () => updateCreditSettings(form ?? {}),
    onSuccess: (data) => {
      queryClient.setQueryData(settingsKey, data);
      setForm(data);
    }
  });

  const numberField = (label: string, key: keyof CreditSettings, min: number, max: number) => (
    <label style={{ display: "grid", gap: 6 }}>
      <span>{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        value={String(form?.[key] ?? "")}
        onChange={(event) => setForm((current) => current ? { ...current, [key]: Number(event.target.value) } : current)}
      />
    </label>
  );

  return (
    <div className="page">
      <PageHeader title="Credit Control" documentTitle="Credit Control" description="Configure customer trade limits, reminders, and monitor outstanding exposure." />
      <Card title="Platform settings" subtitle="The master limit flag is OFF by default after deployment.">
        {form ? (
          <div style={{ display: "grid", gap: 16 }}>
            <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
              <label><input type="checkbox" checked={form.creditLimitEnabled} onChange={(event) => setForm({ ...form, creditLimitEnabled: event.target.checked })} /> Enable credit blocker</label>
              <label><input type="checkbox" checked={form.remindersEnabled} onChange={(event) => setForm({ ...form, remindersEnabled: event.target.checked })} /> Enable reminders</label>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12 }}>
              {numberField("Reminder interval (hours)", "intervalHours", 1, 2160)}
              {numberField("Maximum reminders", "maxCount", 1, 100)}
              {numberField("Quiet start hour", "quietStartHour", 0, 23)}
              {numberField("Quiet end hour", "quietEndHour", 0, 23)}
              {numberField("Threshold (%)", "thresholdPercent", 1, 1000)}
              {numberField("Blocked push cooldown (minutes)", "blockPushCooldownMinutes", 1, 10080)}
            </div>
            <label style={{ display: "grid", gap: 6 }}><span>Reminder message</span><textarea rows={3} value={form.messageTemplate} onChange={(event) => setForm({ ...form, messageTemplate: event.target.value })} /></label>
            <div><Button loading={saveSettings.isPending} onClick={() => saveSettings.mutate()}>Save settings</Button></div>
          </div>
        ) : <p>{settingsQuery.isError ? "Could not load credit settings." : "Loading settings…"}</p>}
      </Card>

      <Card title="Customer limits" subtitle="Used credit includes unpaid invoices and active orders that are not invoiced yet.">
        {customersQuery.isError ? <p>Could not load customer credit data.</p> : (
          <div style={{ overflowX: "auto" }}>
            <table className="table">
              <thead><tr><th>Customer</th><th>Enabled</th><th>Limit</th><th>Days</th><th>Used</th><th>Available</th><th>Status</th><th /></tr></thead>
              <tbody>{(customersQuery.data?.items ?? []).map((customer) => <CreditCustomerRow key={customer.customerId} customer={customer} />)}</tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

export default AdminCreditPage;
