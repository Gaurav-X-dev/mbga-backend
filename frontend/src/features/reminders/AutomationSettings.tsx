import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getAutomationSettings, saveAutomationRule, type AutomationSettings as Settings, type RuleView, type Rule, type ReminderScope } from "../../api/reminders.api";
import { useAuth } from "../../auth/auth-context";
import { Button } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { Checkbox, Field, Input, Select, Textarea } from "../../components/forms/Field";
import { Card } from "../../components/layout/Page";
import { Alert, ErrorState, LoadingSkeleton } from "../../components/feedback/Feedback";
import { normalizeError } from "../../api/errors";
import { useToast } from "../../components/feedback/toast-context";
import { FollowUps } from "./FollowUps";
import "./reminders.css";

const LABELS = { PROXIMITY: "Proximity / visit reminder", INACTIVE: "Inactive customer reminder", PRICING: "Price update reminder" };
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function MultiChoice({ label, options, value, disabled, onChange }: {
  label: string; options: Array<{ value: string; label: string }>; value: string[];
  disabled: boolean; onChange: (value: string[]) => void;
}) {
  const id = useId();
  const selected = options.filter(option => value.includes(option.value));
  return <fieldset className="automation-choice field" disabled={disabled}>
    <legend className="field__label" id={id}>{label}</legend>
    <details className="automation-choice__dropdown">
      <summary aria-labelledby={id}>
        <span>{selected.length ? selected.map(option => option.label).join(", ") : "All"}</span>
        <Icon name="chevronDown" size={16} />
      </summary>
      <div className="automation-choice__options">
        {options.length ? options.map(option => <Checkbox key={option.value} label={option.label}
          checked={value.includes(option.value)} onChange={event => onChange(event.target.checked
            ? [...value, option.value] : value.filter(item => item !== option.value))} />)
          : <p className="meta">No options available for this scope.</p>}
      </div>
    </details>
  </fieldset>;
}

function RuleEditor({ row, settings, scope, canManage }: { row: RuleView; settings: Settings; scope: ReminderScope; canManage: boolean }) {
  const [draft, setDraft] = useState<Rule | null>(null);
  const rule = draft || row.config;
  const [numberInputs, setNumberInputs] = useState<Partial<Record<keyof Rule, string>>>({});
  const toast = useToast();
  const client = useQueryClient();
  const scoped = scope.merchant || Boolean(scope.merchantId);
  const locked = scoped && !row.default.allowMerchantOverride;
  const disabled = !canManage || locked;
  const set = <K extends keyof Rule>(key: K, value: Rule[K]) => setDraft({ ...rule, [key]: value });
  const save = useMutation({ mutationFn: (value: Rule | null) => saveAutomationRule(scope, row.kind, value),
    onSuccess: async () => { setDraft(null); await client.invalidateQueries({ queryKey: ["automation-settings"] }); toast.success("Reminder policy saved."); }
  });
  const number = (key: keyof Rule, label: string, min = 1, max = 8760) => <Field key={key} label={label}><Input type="number" min={min} max={max} step={1} required value={numberInputs[key] ?? String(rule[key])} disabled={disabled || save.isPending} onChange={e => { setNumberInputs(values => ({ ...values, [key]: e.target.value })); set(key, Number(e.target.value)); }} /></Field>;
  const toggle = (key: keyof Rule, label: string) => <Checkbox key={key} label={label} checked={Boolean(rule[key])} disabled={disabled || save.isPending} onChange={e => set(key, e.target.checked)} />;
  const multi = (key: "customerTypes" | "groupIds" | "staffUserIds", label: string, options: Array<{ value: string; label: string }>) =>
    <MultiChoice label={label} options={options} value={rule[key]} disabled={disabled || save.isPending} onChange={value => set(key, value)} />;
  return <Card title={LABELS[row.kind]} subtitle={scoped ? locked ? "Platform-managed · overrides disabled" : row.inherited ? "Using platform default" : "Merchant override" : "Platform default"}>
    <form className="stack" onSubmit={e => { e.preventDefault(); if (draft && !disabled) save.mutate(draft); }}>
      <div className="automation-toggles">{toggle("enabled", "Enable this reminder")}{!scoped ? toggle("allowMerchantOverride", "Allow merchant overrides") : null}{toggle("pushEnabled", "Push notification (in-app always available)")}</div>
      <p className="automation-audience-note">{row.kind === "PROXIMITY" ? "Sent only to the customer when an active, on-duty delivery partner is nearby. No delivery-user notification is sent." : row.kind === "INACTIVE" ? "Sent to the inactive customer and authorized merchant staff, with a separate message for each audience." : "Sent only to merchant staff authorized to manage pricing."}</p>
      <fieldset className="automation-section">
        <legend>Reminder rule</legend>
        <div className="automation-grid">
          {row.kind === "PROXIMITY" ? number("radiusMeters", "Nearby delivery radius (metres)", 1, 100000) : null}
          {number("days", row.kind === "PROXIMITY" ? "Minimum days since last order (0 = any)" : row.kind === "INACTIVE" ? "Days without an order" : "Pricing review interval (days)", row.kind === "PROXIMITY" ? 0 : 1, 3650)}
          {number("intervalHours", "Repeat interval (hours)")}
          {row.kind === "PRICING" ? number("upcomingDays", "Remind before next month (days; 0 disables)", 0, 28) : null}
        </div>
        {row.kind === "PRICING" ? <div className="automation-toggles automation-conditions">{toggle("missingRates", "Check missing prices")}{toggle("staleReview", "Check overdue price reviews")}</div> : null}
      </fieldset>
      <fieldset className="automation-section">
        <legend>Schedule — India time</legend>
        <div className="automation-grid automation-grid--pairs">
          <Field label="Start time"><Select value={String(rule.startHour)} disabled={disabled || save.isPending} onChange={e => set("startHour", Number(e.target.value))} options={Array.from({ length: 24 }, (_, h) => ({ value: String(h), label: `${String(h).padStart(2, "0")}:00` }))} /></Field>
          <Field label="End time"><Select value={String(rule.endHour)} disabled={disabled || save.isPending} onChange={e => set("endHour", Number(e.target.value))} options={Array.from({ length: 24 }, (_, h) => ({ value: String(h), label: `${String(h).padStart(2, "0")}:00` }))} /></Field>
        </div>
        <fieldset disabled={disabled || save.isPending} className="automation-weekdays"><legend className="field__label">Send on</legend>{DAYS.map((label, day) => <Checkbox key={label} label={label} checked={rule.weekdays.includes(day)} onChange={e => set("weekdays", e.target.checked ? [...rule.weekdays, day].sort() : rule.weekdays.filter(d => d !== day))} />)}</fieldset>
      </fieldset>
      {row.kind !== "PRICING" ? <fieldset className="automation-section">
        <legend>Customer audience</legend>
        <div className="automation-grid automation-grid--pairs">
          {multi("customerTypes", "Customer types (empty = all)", settings.customerTypes)}
          {scoped ? multi("groupIds", "Customer groups (empty = all)", settings.groups) : null}
        </div>
        <div className="automation-toggles automation-conditions">
          {toggle("suppressActiveOrders", "Skip customers with an active order")}
          {row.kind === "INACTIVE" || rule.days > 0 ? toggle("includeNeverOrdered", "Include customers who have never ordered") : null}
        </div>
      </fieldset> : null}
      <fieldset className="automation-section automation-messages">
        <legend>Notification messages</legend>
        <Field label="Notification title"><Input maxLength={180} value={rule.title} disabled={disabled || save.isPending} onChange={e => set("title", e.target.value)} required /></Field>
        {row.kind !== "PROXIMITY" ? <Field label="Merchant message"><Textarea maxLength={2000} value={rule.staffTemplate} disabled={disabled || save.isPending} onChange={e => set("staffTemplate", e.target.value)} required /></Field> : null}
        {row.kind !== "PRICING" ? <Field label="Customer message"><Textarea maxLength={2000} value={rule.customerTemplate} disabled={disabled || save.isPending} onChange={e => set("customerTemplate", e.target.value)} required /></Field> : null}
        <p className="meta">Available placeholders: {settings.placeholders.map(p => `{${p}}`).join(", ")}.</p>
      </fieldset>
      <details className="automation-advanced">
        <summary>Advanced delivery controls</summary>
        <div className="automation-grid">
          {number("maxCount", "Maximum reminders per activity period", 1, 100)}
          {number("notificationTtlHours", "Queued push expiry (hours)", 1, 168)}
          {row.kind === "PROXIMITY" ? <>{number("maxLocationAgeSeconds", "Maximum GPS age (seconds)", 10, 3600)}{number("maxAccuracyMeters", "Maximum GPS uncertainty (metres)", 1, 5000)}</> : number("maxSnoozeHours", "Maximum follow-up snooze (hours)")}
          {scoped && row.kind !== "PROXIMITY" ? multi("staffUserIds", "Merchant recipients (empty = all authorized staff)", settings.recipients) : null}
        </div>
      </details>
      {save.isError ? <Alert tone="error">{normalizeError(save.error).userMessage}</Alert> : null}
      {canManage ? <div className="automation-toggles automation-save"><Button type="submit" disabled={!draft || disabled} loading={save.isPending}>Save {LABELS[row.kind].toLowerCase()}</Button>{scoped && row.hasOverride ? <Button variant="secondary" disabled={save.isPending} onClick={() => save.mutate(null)}>Use platform default</Button> : null}</div> : <p className="meta">Read-only access</p>}
    </form>
  </Card>;
}

export function AutomationSettings({ merchant, merchantId }: ReminderScope) {
  const auth = useAuth();
  const scope = { merchant, merchantId };
  const [tab, setTab] = useState("PROXIMITY");
  const [expanded, setExpanded] = useState(false);
  const panelId = useId();
  const query = useQuery({ queryKey: ["automation-settings", scope], queryFn: ({ signal }) => getAutomationSettings(scope, signal), retry: false, enabled: expanded });
  const canManage = auth.can(merchant ? "customers.update" : "platform_settings.manage");
  return <section className="automation-panel card">
    <button type="button" className="automation-panel__trigger" aria-expanded={expanded} aria-controls={panelId} onClick={() => setExpanded(value => !value)}>
      <span className="automation-panel__icon"><Icon name="bell" size={20} /></span>
      <span className="automation-panel__heading"><span>Automated notifications & reminders</span><small>Nearby delivery offers, inactive customers and price updates</small></span>
      <span className="automation-panel__chevron"><Icon name={expanded ? "chevronUp" : "chevronDown"} size={20} /></span>
    </button>
    <div id={panelId} hidden={!expanded} className="automation-panel__body">
    <p className="meta">Rules use India business time. Changes apply to the next evaluation; queued pushes are checked again before sending.</p>
    <div className="automation-tabs" role="tablist" aria-label="Reminder settings">{Object.entries(LABELS).map(([kind, label]) => <Button key={kind} role="tab" aria-selected={tab === kind} variant={tab === kind ? "primary" : "secondary"} onClick={() => setTab(kind)}>{label}</Button>)}</div>
    {query.isLoading ? <LoadingSkeleton rows={4} /> : query.isError ? <Card><ErrorState error={query.error} onRetry={() => void query.refetch()} /></Card> : query.data?.rules.filter(row => row.kind === tab).map(row => <RuleEditor key={`${merchantId || merchant}:${row.kind}:${JSON.stringify(row.config)}:${row.hasOverride}`} row={row} settings={query.data!} scope={scope} canManage={canManage} />)}
    {expanded && (merchant || merchantId) && (auth.can("customers.view") || auth.can("pricing.view")) ? <FollowUps scope={scope} /> : <p className="meta">Select a merchant above to view its follow-ups.</p>}
    </div>
  </section>;
}
