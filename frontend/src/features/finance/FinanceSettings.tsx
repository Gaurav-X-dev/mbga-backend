import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getFinanceSettings, saveFinanceSettings, type FinancePolicy } from "../../api/finance.api";
import { useAuth } from "../../auth/auth-context";
import { Checkbox, Field, Input } from "../../components/forms/Field";
import { Button } from "../../components/common/Button";
import { Alert, ErrorState, LoadingSkeleton } from "../../components/feedback/Feedback";
import { normalizeError } from "../../api/errors";
import "./finance.css";

export function FinanceSettings({ merchantId }: { merchantId?: string }) {
  const auth = useAuth();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<FinancePolicy | null>(null);
  const query = useQuery({ queryKey: ["finance-settings", merchantId], queryFn: ({ signal }) => getFinanceSettings(merchantId, signal), enabled: open });
  const config = draft || query.data?.config;
  const save = useMutation({ mutationFn: (value: FinancePolicy | null) => saveFinanceSettings(merchantId, value), onSuccess: async () => { setDraft(null); await client.invalidateQueries({ queryKey: ["finance-settings"] }); await client.invalidateQueries({ queryKey: ["finance"] }); } });
  const canManage = auth.can("platform_settings.manage");
  return <details className="card finance-settings" onToggle={e => setOpen(e.currentTarget.open)}><summary>Customer advances & driver cash handovers</summary>
    <div className="stack card__body">
      {query.isLoading ? <LoadingSkeleton rows={3} /> : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} /> : config ? <form className="stack" onSubmit={e => { e.preventDefault(); if (draft && canManage) save.mutate(draft); }}>
        <div className="finance-grid">{([['advanceEnabled', 'Enable customer advances'], ['autoUseAdvance', 'Automatically reserve advance for new orders'], ['allowPartialAdvance', 'Use available advance even when it covers only part of an order'], ['handoverEnabled', 'Enable driver cash handover submissions'], ['requireSeparateVerifier', 'Require a different office user to verify deposits and handovers']] as const).map(([key, label]) => <Checkbox key={key} label={label} checked={config[key]} disabled={!canManage || save.isPending} onChange={e => setDraft({ ...config, [key]: e.target.checked })} />)}</div>
        <Field label="Maximum advance deposit (₹)"><Input type="number" min={1} max={100000000} step={1} required value={config.maxDepositAmount} disabled={!canManage || save.isPending} onChange={e => setDraft({ ...config, maxDepositAmount: Number(e.target.value) })} /></Field>
        <p className="meta">Advances are merchant-specific and apply to future orders. Disabling new advances preserves existing held funds until their orders are completed or cancelled. Drivers cannot verify their own cash.</p>
        {save.isError ? <Alert tone="error">{normalizeError(save.error).userMessage}</Alert> : null}
        {canManage ? <div className="finance-actions"><Button type="submit" disabled={!draft} loading={save.isPending}>Save finance settings</Button>{merchantId ? <Button variant="secondary" disabled={save.isPending} onClick={() => save.mutate(null)}>Use platform defaults</Button> : null}</div> : null}
      </form> : null}
    </div>
  </details>;
}
