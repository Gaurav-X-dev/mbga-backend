import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { getCreditSettings, updateCreditSettings, type CreditSettings } from "../../api/credit.api";
import { normalizeError } from "../../api/errors";
import { queryKeys } from "../../api/query-keys";
import { Button } from "../../components/common/Button";
import { Badge } from "../../components/common/StatusBadge";
import { Alert, InlineError, LoadingSkeleton } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Checkbox, Field, Input, Textarea } from "../../components/forms/Field";
import { Card, DetailsPanel } from "../../components/layout/Page";

const hour = (h: number) => `${String(h).padStart(2, "0")}:00`;

function quietWindow(s: Pick<CreditSettings, "quietStartHour" | "quietEndHour">) {
  return `${hour(s.quietStartHour)} – ${hour(s.quietEndHour)}`;
}

const NUMBER_FIELDS: Array<{ key: keyof CreditSettings; label: string; min: number; max: number; hint: string }> = [
  { key: "thresholdPercent", label: "Remind at (% of limit used)", min: 1, max: 1000, hint: "e.g. 80 sends the first reminder at 80% used." },
  { key: "intervalHours", label: "Hours between reminders", min: 1, max: 2160, hint: "Gap before the same customer is reminded again." },
  { key: "maxCount", label: "Reminders per customer", min: 1, max: 100, hint: "Reminders stop after this many." },
  { key: "blockPushCooldownMinutes", label: "Blocked-order alert cooldown (min)", min: 1, max: 10080, hint: "Minimum gap between 'order blocked' pushes." },
  { key: "quietStartHour", label: "Quiet hours start", min: 0, max: 23, hint: "Hour of day (0–23, IST). No reminders from here…" },
  { key: "quietEndHour", label: "Quiet hours end", min: 0, max: 23, hint: "…until this hour." }
];

/** Global credit rules. Only the fields an admin changed are sent back. */
export function CreditSettingsCard({ canManage }: { canManage: boolean }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: queryKeys.credit.settings(), queryFn: ({ signal }) => getCreditSettings(signal) });
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<CreditSettings | null>(null);

  useEffect(() => {
    if (query.data && !editing) setForm(query.data);
  }, [query.data, editing]);

  const changes: Partial<CreditSettings> = {};
  if (form && query.data) {
    (Object.keys(form) as Array<keyof CreditSettings>).forEach((key) => {
      if (form[key] !== query.data[key]) (changes as Record<string, unknown>)[key] = form[key];
    });
  }
  const dirty = Object.keys(changes).length > 0;

  const errors: Record<string, string> = {};
  if (form) {
    for (const field of NUMBER_FIELDS) {
      const value = form[field.key] as number;
      if (!Number.isInteger(value) || value < field.min || value > field.max) errors[field.key] = `${field.min}–${field.max}`;
    }
    if (form.messageTemplate.trim().length < 10) errors.messageTemplate = "At least 10 characters.";
  }
  const valid = Object.keys(errors).length === 0;

  const mutation = useMutation({
    mutationFn: () => updateCreditSettings(changes),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.credit.settings(), saved);
      void queryClient.invalidateQueries({ queryKey: queryKeys.credit.all });
      toast.success("Credit settings saved.");
      setEditing(false);
    }
  });

  const settings = query.data;
  const set = <K extends keyof CreditSettings>(key: K, value: CreditSettings[K]) => setForm((p) => (p ? { ...p, [key]: value } : p));

  return (
    <Card
      title="Credit rules"
      subtitle="Apply to every merchant's customers"
      actions={
        settings ? (
          <span className="row" style={{ gap: 8 }}>
            <Badge tone={settings.creditLimitEnabled ? "success" : "neutral"}>{settings.creditLimitEnabled ? "Limits enforced" : "Limits off"}</Badge>
            {canManage && !editing ? (
              <Button variant="secondary" size="sm" icon="edit" onClick={() => setEditing(true)}>
                Edit
              </Button>
            ) : null}
          </span>
        ) : null
      }
    >
      {query.isLoading || !form ? (
        query.error ? <InlineError error={query.error} onRetry={() => void query.refetch()} /> : <LoadingSkeleton rows={4} label="Loading settings" />
      ) : !editing ? (
        <div className="stack">
          {!settings!.creditLimitEnabled ? (
            <Alert tone="info" title="Credit limits are off — nothing is being blocked">
              <ol style={{ margin: "4px 0 0", paddingLeft: "1.2em" }}>
                <li>Set credit on, a limit and payment days for one test customer (Change limit, below).</li>
                <li>Check their used and available credit in the list.</li>
                <li>Switch on “Enforce credit limits” here.</li>
                <li>Place an order within the limit, then one that goes over it.</li>
                <li>Try a driver increasing an order at the door.</li>
                <li>Record a payment and confirm the available credit goes back up.</li>
              </ol>
            </Alert>
          ) : null}
          <DetailsPanel
            items={[
              {
                label: "Credit limits",
                value: settings!.creditLimitEnabled ? "Enforced for customers with credit on and a limit above ₹0" : "Off — no order is blocked"
              },
              { label: "Reminders", value: settings!.remindersEnabled ? `On, from ${settings!.thresholdPercent}% used` : "Off" },
              { label: "Reminder rhythm", value: `Every ${settings!.intervalHours} h, at most ${settings!.maxCount} times` },
              { label: "Quiet hours", value: quietWindow(settings!) },
              {
                label: "Blocked-order alert cooldown",
                value: `${settings!.blockPushCooldownMinutes} min — repeat attempts are still blocked, just not re-notified`
              },
              { label: "Reminder message", value: <span style={{ whiteSpace: "pre-wrap" }}>{settings!.messageTemplate}</span> }
            ]}
          />
        </div>
      ) : (
        <form
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            if (dirty && valid) mutation.mutate();
          }}
        >
          <Checkbox
            label="Enforce credit limits"
            description="Block new orders that would take a customer past their limit."
            checked={form.creditLimitEnabled}
            onChange={(e) => set("creditLimitEnabled", e.target.checked)}
          />
          <Checkbox
            label="Send low-credit reminders"
            description="Notify customers as they approach their limit."
            checked={form.remindersEnabled}
            onChange={(e) => set("remindersEnabled", e.target.checked)}
          />
          <div className="grid-2">
            {NUMBER_FIELDS.map((field) => (
              <Field key={field.key} label={field.label} hint={field.hint} error={errors[field.key]}>
                <Input
                  type="number"
                  min={field.min}
                  max={field.max}
                  inputMode="numeric"
                  value={String(form[field.key])}
                  onChange={(e) => set(field.key, Number.parseInt(e.target.value, 10) as never)}
                />
              </Field>
            ))}
          </div>
          <Field label="Reminder message" error={errors.messageTemplate} hint="What the customer is sent. 10–1000 characters.">
            <Textarea value={form.messageTemplate} onChange={(e) => set("messageTemplate", e.target.value)} rows={3} maxLength={1000} />
          </Field>
          {form.creditLimitEnabled && !query.data?.creditLimitEnabled ? (
            <Alert tone="warning">
              Saving this starts blocking orders that go over a customer's limit straight away. Make sure test customers are
              configured and their used credit looks right first.
            </Alert>
          ) : null}
          {mutation.error ? <Alert tone="error">{normalizeError(mutation.error).userMessage}</Alert> : null}
          <div className="row" style={{ gap: 8, justifyContent: "flex-end" }}>
            <Button
              variant="secondary"
              onClick={() => {
                setForm(query.data ?? null);
                mutation.reset();
                setEditing(false);
              }}
              disabled={mutation.isPending}
            >
              Cancel
            </Button>
            <Button type="submit" icon="check" disabled={!dirty || !valid} loading={mutation.isPending} loadingText="Saving…">
              Save {dirty ? `${Object.keys(changes).length} change${Object.keys(changes).length === 1 ? "" : "s"}` : "changes"}
            </Button>
          </div>
        </form>
      )}
    </Card>
  );
}
