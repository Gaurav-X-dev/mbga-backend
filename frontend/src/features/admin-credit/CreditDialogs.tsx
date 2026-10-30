import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { approveCreditOverride, getCreditHistory, updateCustomerCredit, type CustomerCredit } from "../../api/credit.api";
import { normalizeError } from "../../api/errors";
import { queryKeys } from "../../api/query-keys";
import { Button } from "../../components/common/Button";
import { Drawer, DrawerSection, Modal } from "../../components/feedback/Dialogs";
import { Alert, ErrorState, LoadingSkeleton } from "../../components/feedback/Feedback";
import { Checkbox, Field, Input, Select, Textarea } from "../../components/forms/Field";
import { DetailsPanel } from "../../components/layout/Page";
import { formatCurrency, formatDateTime, humanize } from "../../utils/format";

function FieldErrors({ error }: { error: unknown }) {
  const e = normalizeError(error);
  const fields = Object.entries(e.fieldErrors ?? {});
  return (
    <Alert tone="error" title={e.userMessage}>
      {fields.length ? (
        <ul style={{ margin: 0, paddingLeft: "1.2em" }}>
          {fields.map(([f, m]) => (
            <li key={f}>
              <strong>{humanize(f)}</strong>: {m}
            </li>
          ))}
        </ul>
      ) : null}
    </Alert>
  );
}

/** Turn credit on or off for one customer and set the limit and terms. Every change needs a reason. */
export function ConfigureCreditDialog({
  customer,
  onClose,
  onSaved
}: {
  customer: CustomerCredit | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({ enabled: false, limit: "", days: "", reason: "" });
  useEffect(() => {
    if (customer)
      setForm({
        enabled: customer.creditEnabled,
        limit: String(customer.creditLimit ?? 0),
        days: customer.creditDays ? String(customer.creditDays) : "",
        reason: ""
      });
  }, [customer]);

  const limit = Number(form.limit);
  const days = form.days ? Number(form.days) : null;
  const errors = {
    limit: !Number.isInteger(limit) || limit < 0 ? "Whole rupees, 0 or more." : undefined,
    days: days !== null && (!Number.isInteger(days) || days < 1 || days > 365) ? "1–365 days." : undefined,
    reason: form.reason.trim().length < 5 ? "At least 5 characters - it is recorded in the audit trail." : undefined
  };
  const valid = !Object.values(errors).some(Boolean);
  const belowUsed = customer && form.enabled && limit < customer.usedCredit;

  const mutation = useMutation({
    mutationFn: () =>
      updateCustomerCredit(customer!.customerId, { creditEnabled: form.enabled, creditLimit: limit, creditDays: days, reason: form.reason.trim() }),
    onSuccess: () => {
      onSaved();
      onClose();
    }
  });

  return (
    <Modal
      open={customer !== null}
      title={customer ? `Credit for ${customer.customerName}` : "Customer credit"}
      description={customer ? `Currently using ${formatCurrency(customer.usedCredit)}.` : undefined}
      onClose={() => {
        mutation.reset();
        onClose();
      }}
      busy={mutation.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button icon="check" onClick={() => valid && mutation.mutate()} disabled={!valid} loading={mutation.isPending} loadingText="Saving…">
            Save
          </Button>
        </>
      }
    >
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) mutation.mutate();
        }}
      >
        <Checkbox
          label="Allow ordering on credit"
          description="Off means every order must be paid as it is delivered."
          checked={form.enabled}
          onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
        />
        <div className="grid-2">
          <Field label="Credit limit (₹)" required error={errors.limit}>
            <Input type="number" min={0} step={1} inputMode="numeric" value={form.limit} onChange={(e) => setForm({ ...form, limit: e.target.value })} disabled={!form.enabled} />
          </Field>
          <Field label="Credit days" optional error={errors.days} hint="Days to pay each invoice.">
            <Input type="number" min={1} max={365} inputMode="numeric" value={form.days} onChange={(e) => setForm({ ...form, days: e.target.value })} disabled={!form.enabled} />
          </Field>
        </div>
        {form.enabled && limit === 0 ? (
          <Alert tone="info">With a ₹0 limit this customer's orders are not checked at all. Set a limit above ₹0 to enforce one.</Alert>
        ) : null}
        {belowUsed ? (
          <Alert tone="warning">
            The new limit is below what they already owe ({formatCurrency(customer!.usedCredit)}). Their own orders (and driver increases at the door) will be refused until they pay down, once limits are switched on globally.
          </Alert>
        ) : null}
        <Field label="Reason" required error={form.reason ? errors.reason : undefined} hint="Recorded in the credit history.">
          <Textarea value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} rows={2} maxLength={500} placeholder="e.g. Limit approved by finance team" />
        </Field>
        {mutation.error ? <FieldErrors error={mutation.error} /> : null}
      </form>
    </Modal>
  );
}

const VALIDITY = [
  { value: "15", label: "15 minutes" },
  { value: "30", label: "30 minutes" },
  { value: "60", label: "1 hour" },
  { value: "240", label: "4 hours" },
  { value: "720", label: "12 hours" },
  { value: "1440", label: "24 hours" }
];

/** A one-off allowance above the limit, for an order that cannot wait. It expires on its own. */
export function OverrideDialog({
  customer,
  onClose,
  onApproved
}: {
  customer: CustomerCredit | null;
  onClose: () => void;
  onApproved: (message: string) => void;
}) {
  const [form, setForm] = useState({ amount: "", reason: "", minutes: "30" });
  useEffect(() => {
    if (customer) setForm({ amount: "", reason: "", minutes: "30" });
  }, [customer]);

  const amount = Number(form.amount);
  const errors = {
    amount: !(Number.isInteger(amount) && amount > 0) ? "Whole rupees, more than 0." : undefined,
    reason: form.reason.trim().length < 5 ? "At least 5 characters." : undefined
  };
  const valid = !Object.values(errors).some(Boolean);

  const mutation = useMutation({
    mutationFn: () => approveCreditOverride(customer!.customerId, { amount, reason: form.reason.trim(), validForMinutes: Number(form.minutes) }),
    onSuccess: (override) => {
      onApproved(`${formatCurrency(override.amount)} extra approved for ${customer?.customerName ?? "the customer"} until ${formatDateTime(override.expiresAt)}.`);
      onClose();
    }
  });

  return (
    <Modal
      open={customer !== null}
      title={customer ? `Temporary override · ${customer.customerName}` : "Temporary override"}
      description="Adds to this customer's limit for one order. Once an order uses it, or the time runs out, it no longer applies."
      onClose={() => {
        mutation.reset();
        onClose();
      }}
      busy={mutation.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button icon="check" onClick={() => valid && mutation.mutate()} disabled={!valid} loading={mutation.isPending} loadingText="Approving…">
            Approve {amount > 0 ? formatCurrency(amount) : "override"}
          </Button>
        </>
      }
    >
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) mutation.mutate();
        }}
      >
        {customer ? (
          <DetailsPanel
            items={[
              { label: "Limit", value: formatCurrency(customer.creditLimit) },
              { label: "Used", value: formatCurrency(customer.usedCredit) },
              { label: "Available", value: <strong>{formatCurrency(customer.availableCredit)}</strong> },
              {
                label: "Limit while active",
                value: amount > 0 ? <strong>{formatCurrency(customer.creditLimit + amount)}</strong> : "—",
                hidden: !(amount > 0)
              }
            ]}
          />
        ) : null}
        <div className="grid-2">
          <Field label="Extra amount (₹)" required error={form.amount ? errors.amount : undefined}>
            <Input type="number" min={1} step={1} inputMode="numeric" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} autoFocus />
          </Field>
          <Field label="Valid for" required>
            <Select value={form.minutes} onChange={(e) => setForm({ ...form, minutes: e.target.value })} options={VALIDITY} />
          </Field>
        </div>
        <Field label="Reason" required error={form.reason ? errors.reason : undefined} hint="Recorded in the credit history.">
          <Textarea value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} rows={2} maxLength={500} placeholder="e.g. Emergency order approved by administrator" />
        </Field>
        {mutation.error ? <FieldErrors error={mutation.error} /> : null}
      </form>
    </Modal>
  );
}

const TIME_KEYS = ["createdAt", "created_at", "changedAt", "sentAt", "approvedAt", "at", "timestamp", "expiresAt"];
const HIDDEN_KEYS = new Set(["id", "customerId", "customer_id", "merchantId", "merchant_id"]);

function formatValue(key: string, value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return /amount|limit|credit|used|available|balance/i.test(key) && !/days|count|percent/i.test(key) ? formatCurrency(value) : String(value);
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) return formatDateTime(value);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** The history entries are rendered generically: the backend owns their shape. */
function HistoryList({ items, empty }: { items: Array<Record<string, unknown>>; empty: string }) {
  if (!items.length) return <p className="text-muted text-small">{empty}</p>;
  return (
    <ol className="timeline">
      {items.map((item, index) => {
        const timeKey = TIME_KEYS.find((k) => typeof item[k] === "string");
        const rest = Object.entries(item).filter(([k]) => k !== timeKey && !HIDDEN_KEYS.has(k));
        return (
          <li key={String(item.id ?? index)}>
            {timeKey ? <div className="text-muted text-small">{formatDateTime(String(item[timeKey]))}</div> : null}
            <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "max-content 1fr", gap: "2px 12px" }}>
              {rest.map(([k, v]) => (
                <div key={k} style={{ display: "contents" }}>
                  <dt className="text-muted text-small">{humanize(k.replace(/([a-z])([A-Z])/g, "$1_$2"))}</dt>
                  <dd className="text-small" style={{ margin: 0, wordBreak: "break-word" }}>
                    {formatValue(k, v)}
                  </dd>
                </div>
              ))}
            </dl>
          </li>
        );
      })}
    </ol>
  );
}

export function CreditHistoryDrawer({ customer, onClose }: { customer: CustomerCredit; onClose: () => void }) {
  const query = useQuery({
    queryKey: queryKeys.credit.history(customer.customerId),
    queryFn: ({ signal }) => getCreditHistory(customer.customerId, signal)
  });
  return (
    <Drawer open size="lg" title={`Credit history · ${customer.customerName}`} subtitle="Limit changes, overrides and reminders sent" onClose={onClose}>
      {query.isLoading ? (
        <LoadingSkeleton rows={6} label="Loading history" />
      ) : query.error || !query.data ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          <DrawerSection title={`Limit changes (${query.data.settingsAudit?.length ?? 0})`}>
            <HistoryList items={query.data.settingsAudit ?? []} empty="The limit has never been changed." />
          </DrawerSection>
          <DrawerSection title={`Overrides (${query.data.overrides?.length ?? 0})`}>
            <HistoryList items={query.data.overrides ?? []} empty="No temporary overrides have been approved." />
          </DrawerSection>
          <DrawerSection title={`Reminders sent (${query.data.notifications?.length ?? 0})`}>
            <HistoryList items={query.data.notifications ?? []} empty="No credit reminders have been sent." />
          </DrawerSection>
        </>
      )}
    </Drawer>
  );
}
