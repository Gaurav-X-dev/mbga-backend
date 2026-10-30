import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getAppSettings, settingsPath, updateAppSettings } from "../../api/app-settings.api";
import { listMerchants } from "../../api/merchants.api";
import { normalizeError } from "../../api/errors";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { Alert, InlineError, LoadingSkeleton } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Checkbox, Field, Input, Select } from "../../components/forms/Field";
import { Card, PageHeader } from "../../components/layout/Page";
import { CreditSettingsCard } from "../admin-credit/CreditSettingsCard";

const KEY = ["app-settings"] as const;

function RadiusCard({ merchant, merchantId, canManage }: { merchant: boolean; merchantId?: string; canManage: boolean }) {
  const path = settingsPath(merchant, merchantId);
  const scoped = merchant || Boolean(merchantId);
  const client = useQueryClient();
  const toast = useToast();
  const query = useQuery({ queryKey: [...KEY, path], queryFn: ({ signal }) => getAppSettings(path, signal) });
  const [draft, setDraft] = useState<string | null>(null);
  const [inherit, setInherit] = useState<boolean | null>(null);
  const data = query.data;
  const value = draft ?? String(data?.deliveryRadiusMeters ?? 300);
  const useDefault = inherit ?? data?.overrideRadiusMeters === null;
  const radius = Number(value);
  const valid = scoped && useDefault || Number.isInteger(radius) && radius >= 1 && radius <= 100000;
  const dirty = Boolean(data && (scoped && useDefault
    ? data.overrideRadiusMeters !== null
    : radius !== data.deliveryRadiusMeters || scoped && data.overrideRadiusMeters === null));
  const mutation = useMutation({
    mutationFn: () => updateAppSettings(path, { deliveryRadiusMeters: scoped && useDefault ? null : radius }),
    onSuccess: (saved) => {
      client.setQueryData([...KEY, path], saved);
      setDraft(null); setInherit(null);
      void client.invalidateQueries({ queryKey: KEY });
      toast.success("Delivery radius saved. Applies to the next arrival check.");
    }
  });
  return <Card title={scoped ? "Agency delivery radius" : "Default delivery radius"}
    subtitle={scoped ? "Applies only to this agency" : "Applies to agencies using the platform default"}>
    {query.isLoading ? <LoadingSkeleton rows={3} /> : query.error ? <InlineError error={query.error} onRetry={() => void query.refetch()} /> : data ?
      <form className="stack" onSubmit={(event) => { event.preventDefault(); if (valid && dirty && canManage) mutation.mutate(); }}>
        {scoped ? <Checkbox label={`Use platform default (${(data.defaultRadiusMeters ?? 300) / 1000} km)`}
          checked={useDefault} disabled={!canManage || mutation.isPending} onChange={(event) => setInherit(event.target.checked)} /> : null}
        <Field label="Arrival radius (metres)" required error={!valid ? "Enter a whole number from 1 to 100000 metres." : undefined}
          hint={`${(scoped && useDefault ? data.defaultRadiusMeters ?? 300 : radius) / 1000} km allowed around the saved delivery location.`}>
          <Input type="number" min={1} max={100000} step={1} value={scoped && useDefault ? data.defaultRadiusMeters ?? 300 : value}
            disabled={!canManage || mutation.isPending || scoped && useDefault} onChange={(event) => setDraft(event.target.value)} />
        </Field>
        <p className="meta">Drivers must be within this radius to mark “I am on location”. A saved delivery location is required.</p>
        {mutation.error ? <Alert tone="error">{normalizeError(mutation.error).userMessage}</Alert> : null}
        {canManage ? <div><Button type="submit" disabled={!valid || !dirty} loading={mutation.isPending}>Save radius</Button></div> : <p className="meta">You have read-only access.</p>}
      </form> : null}
  </Card>;
}

function CutoffCard({ canManage }: { canManage: boolean }) {
  const client = useQueryClient();
  const toast = useToast();
  const query = useQuery({ queryKey: [...KEY, "/admin/settings"], queryFn: ({ signal }) => getAppSettings("/admin/settings", signal) });
  const [draft, setDraft] = useState<string | null>(null);
  const value = draft ?? String(query.data?.orderCutoffHour ?? 16);
  const mutation = useMutation({
    mutationFn: () => updateAppSettings("/admin/settings", { orderCutoffHour: Number(value) }),
    onSuccess: () => { setDraft(null); void client.invalidateQueries({ queryKey: KEY }); toast.success("Order cut-off saved."); }
  });
  return <Card title="Order scheduling" subtitle="Platform-wide order cut-off in India Standard Time">
    {query.isLoading ? <LoadingSkeleton rows={2} /> : query.error ? <InlineError error={query.error} onRetry={() => void query.refetch()} /> :
      <form className="stack" onSubmit={(event) => { event.preventDefault(); if (canManage) mutation.mutate(); }}>
        <Field label="Order cut-off (IST)" hint="Applies to new orders. Existing delivery promises stay unchanged.">
          <Select value={value} disabled={!canManage || mutation.isPending} onChange={(event) => setDraft(event.target.value)}
            options={Array.from({ length: 24 }, (_, hour) => ({ value: String(hour), label: `${String(hour).padStart(2, "0")}:00 IST` }))} />
        </Field>
        {mutation.error ? <Alert tone="error">{normalizeError(mutation.error).userMessage}</Alert> : null}
        {canManage ? <div><Button type="submit" disabled={Number(value) === query.data?.orderCutoffHour} loading={mutation.isPending}>Save cut-off</Button></div> : null}
      </form>}
  </Card>;
}

export function AppSettingsPage() {
  const auth = useAuth();
  const merchant = auth.channel === "merchant";
  const [merchantId, setMerchantId] = useState("");
  const canManage = auth.can(merchant ? PERMISSIONS.deliveryConfirm : PERMISSIONS.platformSettingsManage);
  const agencies = useQuery({ queryKey: [...KEY, "agencies"], queryFn: ({ signal }) => listMerchants({ limit: 100, offset: 0 }, signal),
    enabled: !merchant && auth.can(PERMISSIONS.merchantsView) });
  return <div className="page stack">
    <PageHeader title="App Settings" documentTitle="App Settings" description="Manage delivery arrival rules and existing app operating settings." />
    {!merchant && auth.can(PERMISSIONS.merchantsView) ? <Card title="Delivery settings scope">
      <Field label="Apply delivery settings to">
        <Select value={merchantId} onChange={(event) => setMerchantId(event.target.value)} options={[
          { value: "", label: "Platform default" }, ...(agencies.data?.items ?? []).map((agency) => ({ value: agency.id, label: agency.business_name }))
        ]} />
      </Field>
      {agencies.error ? <InlineError error={agencies.error} onRetry={() => void agencies.refetch()} /> : null}
    </Card> : null}
    <RadiusCard key={merchantId} merchant={merchant} merchantId={merchantId || undefined} canManage={canManage} />
    {!merchant ? <>
      <CutoffCard canManage={canManage} />
      {auth.can(PERMISSIONS.creditView) ? <CreditSettingsCard canManage={auth.can(PERMISSIONS.creditManage)} /> : null}
      <Card title="More app configuration"><div className="stack">
        {auth.can(PERMISSIONS.catalogueView) ? <Link to="/admin/catalogue">Business Catalogue — app dropdowns and cylinder types</Link> : null}
        <Link to="/admin/privacy-policy">Privacy Policy — customer app content</Link>
      </div></Card>
    </> : null}
  </div>;
}
