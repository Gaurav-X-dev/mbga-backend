import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { competitorPricingApi as defaultApi, type CompetitorPricingApi, type Competitor, type ComparisonRow, type MarketFilters, type DepotAddress } from "../../api/competitor-pricing.api";
import type { Address } from "../../api/orders.api";
import { normalizeError } from "../../api/errors";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { Modal, ConfirmationDialog } from "../../components/feedback/Dialogs";
import { Alert, InlineError } from "../../components/feedback/Feedback";
import { Field, Input, Select, Textarea } from "../../components/forms/Field";
import { GoogleMapLocationPicker } from "../../components/maps/GoogleMapLocationPicker";
import { formatCurrency as money } from "../../utils/format";
import { cylinders, customers, today, validPrice } from "./market-options";

export function PricingForm({ api = defaultApi, channel = "merchant", merchantId, kind, row, competitor, filters, brands, onClose, onSaved }: {
  api?: CompetitorPricingApi; channel?: "merchant" | "admin"; merchantId?: string;
  kind: "survey" | "benchmark" | "brand" | "depot"; row?: ComparisonRow; competitor?: Competitor;
  filters: MarketFilters; brands: Competitor[]; onClose: () => void; onSaved: () => Promise<void>;
}) {
  const auth = useAuth();
  const client = useQueryClient();
  const [market, setMarket] = useState(filters);
  const [price, setPrice] = useState(row ? String(row.price) : "");
  const [brandId, setBrandId] = useState(competitor?.id ?? row?.competitorId ?? "");
  const [date, setDate] = useState(today());
  const [notes, setNotes] = useState(competitor?.notes ?? row?.notes ?? "");
  const [name, setName] = useState("");
  const [color, setColor] = useState("#8B5CF6");
  const [address, setAddress] = useState<Address>({ ...(competitor?.depotAddress ?? {}), line1: competitor?.depotAddress?.line1 ?? undefined, city: competitor?.depotAddress?.city ?? undefined, state: competitor?.depotAddress?.state ?? undefined, pincode: competitor?.depotAddress?.pincode ?? undefined });
  const [useMap, setUseMap] = useState(false);
  const [addRate, setAddRate] = useState(false);
  const [createdId, setCreatedId] = useState("");
  const [duplicate, setDuplicate] = useState(false);
  const [existing, setExisting] = useState("");
  const [candidates, setCandidates] = useState(brands);
  const [validation, setValidation] = useState<Record<string, string>>({});
  const [confirm, setConfirm] = useState(false);
  const record = kind === "survey" || (kind === "brand" && addRate);
  const canRecord = auth.can(PERMISSIONS.pricingManage) || auth.can(PERMISSIONS.competitorPricingRecord);
  const validMarket = /^[1-9]\d{5}$/.test(market.pincode);
  const preview = useQuery({ queryKey: [channel, "competitor-pricing", merchantId ?? auth.user?.merchant?.id ?? auth.user?.user_id, "snapshot", market], queryFn: ({ signal }) => api.snapshot(market, signal), enabled: record && validMarket });
  const depot = (): DepotAddress => ({ line1: address.line1 || null, line2: address.line2 || null, city: address.city || null, state: address.state || null, pincode: address.pincode || null, latitude: address.latitude ?? null, longitude: address.longitude ?? null });
  const hasDepot = Object.values(depot()).some(value => value !== null);
  const mutation = useMutation({ retry: false, mutationFn: async () => {
    if (kind === "depot" && competitor) { await api.updateDepot(competitor.id, hasDepot ? depot() : null, notes); return; }
    if (kind === "benchmark") { await api.benchmark({ cylinderType: filters.cylinderType, price: Number(price), notes }); return; }
    let selected = brandId;
    if (kind === "brand") {
      selected = createdId || existing;
      if (!selected) {
        try {
          const brand = await api.createBrand({ name: name.trim(), color, notes, ...(hasDepot ? { depotAddress: depot() } : {}) });
          selected = brand.id;
          setCreatedId(brand.id);
          void client.invalidateQueries({ queryKey: [channel, "competitor-pricing", merchantId ?? auth.user?.merchant?.id ?? auth.user?.user_id] });
        } catch (error) {
          if (normalizeError(error).status === 409) {
            setDuplicate(true);
            setCandidates(await api.brands(""));
          }
          throw error;
        }
      }
    }
    if (record) await api.survey({ competitorId: selected, cylinderType: market.cylinderType, customerType: market.customerType, locationPincode: market.pincode, price: Number(price), effectiveDate: date, notes });
  } });
  async function save() {
    try { await mutation.mutateAsync(); await onSaved(); } catch { setConfirm(false); }
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (mutation.isPending) return;
    const errors: Record<string, string> = {};
    if ((record || kind === "benchmark") && !validPrice(price)) errors.price = "Enter a positive price with at most two decimal places.";
    if (kind === "brand" && !name.trim() && !createdId && !existing) errors.name = "Enter a competitor name.";
    if (record && !validMarket) errors.pincode = "Enter a valid six-digit pincode.";
    if (record && (!date || date > today())) errors.effectiveDate = "Effective date cannot be later than today.";
    if (kind === "brand" && existing && !record) errors.name = "Enable initial rate capture before selecting an existing brand.";
    if (kind === "survey" && !brandId) errors.competitorId = "Select an active competitor.";
    if (address.pincode && !/^[1-9]\d{5}$/.test(address.pincode)) errors.depotAddress = "Enter a valid depot pincode.";
    setValidation(errors);
    if (Object.keys(errors).length) return;
    if (kind === "benchmark") setConfirm(true); else void save();
  }
  const fieldErrors = { ...normalizeError(mutation.error).fieldErrors, ...validation };
  const current = kind === "benchmark" ? row?.price : preview.data?.mbgaPrice;
  const difference = current === undefined ? null : Number(price) - current;
  const title = kind === "brand" ? "Add competitor" : kind === "depot" ? "Edit competitor depot" : kind === "benchmark" ? "Edit MBGA selling rate" : "Record competitor survey";
  return <>
    <Modal open={!confirm} title={title} wide={useMap} description={kind === "brand" ? "Register a brand, optionally capture its first rate and depot location." : kind === "depot" ? competitor?.name : `${cylinders.find(c => c.value === market.cylinderType)?.label} · ${market.customerType} · ${market.pincode}`} onClose={onClose} busy={mutation.isPending} footer={<><Button variant="secondary" disabled={mutation.isPending} onClick={onClose}>Cancel</Button><Button type="submit" form="market-price-form" loading={mutation.isPending}>{kind === "depot" ? "Save depot" : kind === "brand" ? createdId ? "Retry rate save" : "Save competitor" : "Save rate"}</Button></>}>
      <form id="market-price-form" className="stack" onSubmit={submit}>
        {kind === "brand" && <>
          <Field label="Competitor name" required error={fieldErrors.name}><Input required={!existing && !createdId} disabled={Boolean(createdId || existing)} maxLength={160} value={name} onChange={e => setName(e.target.value)} /></Field>
          <Field label="Brand color"><Input type="color" disabled={Boolean(createdId || existing)} value={color} onChange={e => setColor(e.target.value)} /></Field>
          {canRecord && <label className="market-checkbox"><input type="checkbox" disabled={Boolean(createdId)} checked={addRate} onChange={e => setAddRate(e.target.checked)} /> Also record initial rate</label>}
          {duplicate && canRecord && <Alert tone="warning">A competitor with this code already exists. Check the directory and explicitly select the correct active brand. Its depot details will not be overwritten.<Select aria-label="Use existing competitor" value={existing} onChange={e => setExisting(e.target.value)} placeholder="Choose the existing brand" options={candidates.filter(b => b.status === "ACTIVE").map(b => ({ value: b.id, label: `${b.name} (${b.code})` }))} /></Alert>}
          {createdId && <Alert tone="warning">The brand was created successfully, but its rate has not been saved. Retry to save the rate without creating another brand.</Alert>}
        </>}
        {(kind === "brand" || kind === "depot") && !existing && !createdId && <>
          <Button variant="secondary" onClick={() => setUseMap(!useMap)}>{useMap ? "Hide map" : "Choose depot on map"}</Button>
          {useMap ? <GoogleMapLocationPicker value={address} onChange={next => { setAddress(next); if (next.pincode) setMarket(previous => ({ ...previous, pincode: next.pincode! })); }} prefix="Depot" locationChannel={channel} postalOnly merchantId={merchantId ?? String(auth.user?.merchant?.id ?? "")} /> : <div className="market-filters">
            <Field label="Depot street"><Input maxLength={255} value={address.line1 ?? ""} onChange={e => setAddress({ ...address, line1: e.target.value })} /></Field>
            <Field label="Depot landmark"><Input maxLength={255} value={address.line2 ?? ""} onChange={e => setAddress({ ...address, line2: e.target.value })} /></Field>
            <Field label="Depot city"><Input maxLength={100} value={address.city ?? ""} onChange={e => setAddress({ ...address, city: e.target.value })} /></Field>
            <Field label="Depot state"><Input maxLength={100} value={address.state ?? ""} onChange={e => setAddress({ ...address, state: e.target.value })} /></Field>
            <Field label="Depot pincode" error={fieldErrors.depotAddress}><Input maxLength={6} inputMode="numeric" value={address.pincode ?? ""} onChange={e => { setAddress({ ...address, pincode: e.target.value }); }} /></Field>
          </div>}
        </>}
        {kind === "survey" && <Field label="Competitor" required error={fieldErrors.competitorId}><Select required placeholder="Select a competitor" value={brandId} onChange={e => setBrandId(e.target.value)} options={brands.filter(b => b.status === "ACTIVE").map(b => ({ value: b.id, label: b.name }))} /></Field>}
        {record && <div className="market-filters">
          <Field label="Survey cylinder" required><Select options={cylinders} value={market.cylinderType} onChange={e => setMarket({ ...market, cylinderType: e.target.value })} /></Field>
          <Field label="Survey segment" required><Select options={customers} value={market.customerType} onChange={e => setMarket({ ...market, customerType: e.target.value })} /></Field>
          <Field label="Survey pincode" required error={fieldErrors.pincode ?? fieldErrors.locationPincode}><Input required inputMode="numeric" maxLength={6} pattern="[1-9][0-9]{5}" value={market.pincode} onChange={e => setMarket({ ...market, pincode: e.target.value })} /></Field>
        </div>}
        {(record || kind === "benchmark") && <>
          <Field label="Selling price (₹)" required error={fieldErrors.price}><Input required type="number" min="0.01" step="0.01" max="99999999.99" value={price} onChange={e => setPrice(e.target.value)} /></Field>
          {record && <Field label="Effective date" required error={fieldErrors.effectiveDate}><Input required type="date" max={today()} min={row?.effectiveDate} value={date} onChange={e => setDate(e.target.value)} /></Field>}
          {kind === "benchmark" && <Alert tone="info">This updates the merchant's STANDARD rate across all locations and segments.{validPrice(price) && current !== undefined && <p>Current {money(current)} → {money(Number(price))} · {money(Number(difference))} {current > 0 ? `(${(Number(difference) / current * 100).toFixed(1)}%)` : ""}</p>}</Alert>}
          {record && validPrice(price) && current !== undefined && <Alert tone={difference === 0 ? "info" : Number(difference) > 0 ? "success" : "warning"} title={difference === 0 ? "Price parity" : Number(difference) > 0 ? "Price advantage" : "Competitor is cheaper"}>MBGA {money(current)} · Quote {money(Number(price))} · Gap {money(Math.abs(Number(difference)))}{Number(price) > 0 ? ` (${(Math.abs(Number(difference)) / Number(price) * 100).toFixed(1)}% of quote)` : ""}. {difference === 0 ? "Highlight delivery, safety, and service." : Number(difference) > 0 ? "Highlight the price savings." : "Review your offer before quoting customers."}</Alert>}
          <InlineError error={preview.error} />
        </>}
        <Field label="Notes" optional error={fieldErrors.notes}><Textarea maxLength={4000} rows={3} value={notes} onChange={e => setNotes(e.target.value)} /></Field>
        <p className="text-muted">Recorded by {auth.user?.display_name || "your signed-in account"}{auth.user?.role ? ` (${auth.user.role})` : ""}. Identity is verified by the server.</p>
        <InlineError error={mutation.error} />
      </form>
    </Modal>
    {confirm && <ConfirmationDialog open title="Confirm MBGA rate change" description={`Update the STANDARD rate to ${money(Number(price))} for this cylinder across all markets?`} confirmLabel="Confirm rate change" confirmVariant="primary" onClose={() => setConfirm(false)} onConfirm={async () => { await mutation.mutateAsync(); await onSaved(); }} />}
  </>;
}
