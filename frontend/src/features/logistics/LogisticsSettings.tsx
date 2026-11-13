import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getLogisticsSettings, saveLogisticsSettings, type LogisticsPolicy } from "../../api/logistics.api";
import { useAuth } from "../../auth/auth-context";
import { Button } from "../../components/common/Button";
import { Checkbox, Field, Input, Select } from "../../components/forms/Field";
import { Alert, ErrorState } from "../../components/feedback/Feedback";
import { AppError, normalizeError } from "../../api/errors";
import "./logistics.css";
export function LogisticsSettings({ merchantId }: {
    merchantId?: string;
}) {
    const auth = useAuth();
    const cache = useQueryClient();
    const [open, setOpen] = useState(false);
    const [draft, setDraft] = useState<LogisticsPolicy | null>(null);
    const query = useQuery({ queryKey: ["logistics-settings", merchantId], queryFn: ({ signal }) => getLogisticsSettings(merchantId, signal), enabled: open });
    const [coordinateDraft, setCoordinateDraft] = useState<Record<string, {
        latitude: string;
        longitude: string;
    }>>({});
    const config = draft || query.data?.config;
    const enabled = auth.can("platform_settings.manage");
    const save = useMutation({ mutationFn: (value: LogisticsPolicy | null) => {
            if (value) {
                value = { ...value };
                const codes = value.priorities.map(p => p.code);
                if (new Set(codes).size !== codes.length || !codes.includes(value.defaultPriority))
                    throw new AppError({ kind: "validation", userMessage: "Use unique priority codes and select a default from the same list." });
                for (const key of ['defaultOrigin', 'defaultDestination'] as const) {
                    const p = coordinateDraft[key];
                    if (!p)
                        continue;
                    if (!p.latitude && !p.longitude)
                        value[key] = null;
                    else if (!p.latitude || !p.longitude)
                        throw new AppError({ kind: "validation", userMessage: "Enter both latitude and longitude, or clear both." });
                    else
                        value[key] = { latitude: Number(p.latitude), longitude: Number(p.longitude) };
                }
            }
            return saveLogisticsSettings(merchantId, value);
        }, onSuccess: async () => { setDraft(null); setCoordinateDraft({}); await cache.invalidateQueries({ queryKey: ["logistics-settings"] }); await cache.invalidateQueries({ queryKey: ["logistics"] }); } });
    const change = <K extends keyof LogisticsPolicy>(key: K, value: LogisticsPolicy[K]) => config && setDraft({ ...config, [key]: value });
    return <details className="card logistics-settings" onToggle={e => setOpen(e.currentTarget.open)}><summary>Customer priorities, trips & vehicle returns</summary><div className="card__body stack">
 {query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()}/> : !config ? <p>Loading policy…</p> : <form className="stack" onSubmit={e => {
                e.preventDefault();
                if (config && (draft || Object.keys(coordinateDraft).length))
                    save.mutate(config);
            }}>
 <fieldset disabled={!enabled || save.isPending} className="logistics-fieldset"><legend>Priority labels — lowest rank is most urgent</legend><div className="stack">{config.priorities.map((p, i) => <div className="logistics-priority-row" key={i}><Field label="Code"><Input required pattern="[A-Z][A-Z0-9_]{0,29}" maxLength={30} value={p.code} onChange={e => change("priorities", config.priorities.map((v, j) => j === i ? { ...v, code: e.target.value.toUpperCase() } : v))}/></Field><Field label="Label"><Input required maxLength={40} value={p.label} onChange={e => change("priorities", config.priorities.map((v, j) => j === i ? { ...v, label: e.target.value } : v))}/></Field><Field label="Rank"><Input type="number" min={0} max={100} step={1} value={p.rank} onChange={e => change("priorities", config.priorities.map((v, j) => j === i ? { ...v, rank: Number(e.target.value) } : v))}/></Field><Field label="Color"><Input type="color" value={p.color} onChange={e => change("priorities", config.priorities.map((v, j) => j === i ? { ...v, color: e.target.value } : v))}/></Field><Button variant="secondary" disabled={config.priorities.length <= 1} onClick={() => change("priorities", config.priorities.filter((_, j) => j !== i))}>Remove</Button></div>)}</div><Button variant="secondary" disabled={config.priorities.length >= 12} onClick={() => change("priorities", [...config.priorities, { code: `PRIORITY_${config.priorities.length + 1}`, label: "New priority", rank: config.priorities.length, color: "#64748B" }])}>Add priority</Button></fieldset>
 <div className="form-grid"><Field label="Default customer priority"><Select disabled={!enabled} value={config.defaultPriority} options={config.priorities.map(p => ({ value: p.code, label: p.label }))} onChange={e => change("defaultPriority", e.target.value)}/></Field><Field label="Maximum stops per trip"><Input disabled={!enabled} required type="number" min={1} max={25} step={1} value={config.maxStops} onChange={e => change("maxStops", Number(e.target.value))}/></Field><Field label="Loading cylinder-count ceiling" hint="An operational ceiling; check the vehicle’s rated capacity separately."><Input disabled={!enabled} required type="number" min={1} max={100000} step={1} value={config.maxLoadCylinders} onChange={e => change("maxLoadCylinders", Number(e.target.value))}/></Field></div>
 <div className="form-grid">{([['optimizationEnabled', 'Enable road-route optimization'], ['priorityFirst', 'Prefer priority groups when suggesting routes'], ['requireSeparateReturnVerifier', 'Require separate office return verifier'], ['requireOdometer', 'Require dispatch and return odometer readings']] as const).map(([key, label]) => <Checkbox key={key} disabled={!enabled} label={label} checked={config[key]} onChange={e => change(key, e.target.checked)}/>)}</div>
 {!query.data?.routingConfigured ? <Alert tone="info">Road optimization needs a server routing-provider key. Manual trip sequencing works without it.</Alert> : null}
 {(['defaultOrigin', 'defaultDestination'] as const).map(key => <div key={key} className="form-grid"><Field label={`${key === 'defaultOrigin' ? 'Default dispatch' : 'Default return'} latitude`}><Input type="number" step="any" min={-90} max={90} disabled={!enabled} value={coordinateDraft[key]?.latitude ?? (config[key] ? String(config[key]!.latitude) : '')} onChange={e => setCoordinateDraft({ ...coordinateDraft, [key]: { latitude: e.target.value, longitude: coordinateDraft[key]?.longitude ?? (config[key] ? String(config[key]!.longitude) : '') } })}/></Field><Field label="Longitude"><Input type="number" step="any" min={-180} max={180} disabled={!enabled} value={coordinateDraft[key]?.longitude ?? (config[key] ? String(config[key]!.longitude) : '')} onChange={e => setCoordinateDraft({ ...coordinateDraft, [key]: { longitude: e.target.value, latitude: coordinateDraft[key]?.latitude ?? (config[key] ? String(config[key]!.latitude) : '') } })}/></Field></div>)}
 {save.isError ? <Alert tone="error">{normalizeError(save.error).userMessage}</Alert> : null}{enabled ? <div className="row"><Button type="submit" disabled={!draft && !Object.keys(coordinateDraft).length} loading={save.isPending}>Save logistics settings</Button>{merchantId ? <Button variant="secondary" onClick={() => save.mutate(null)}>Use platform default</Button> : null}</div> : null}
 </form>}</div></details>;
}
