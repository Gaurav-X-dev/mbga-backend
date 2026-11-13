import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Line, LineChart, ResponsiveContainer, CartesianGrid, XAxis, YAxis, Tooltip, Legend } from "recharts";
import { competitorPricingApi as defaultApi, type CompetitorPricingApi, type Competitor, type ComparisonRow, type MarketFilters, type Timeframe } from "../../api/competitor-pricing.api";
import { queryKeys } from "../../api/query-keys";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { Tabs } from "../../components/common/Tabs";
import { Modal, ConfirmationDialog } from "../../components/feedback/Dialogs";
import { Alert, EmptyState, InlineError, LoadingSkeleton } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Input, Select } from "../../components/forms/Field";
import { Card, PageHeader, StatCard } from "../../components/layout/Page";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import { formatCurrency, formatDateTime } from "../../utils/format";
import { lookupPincode } from "../../api/locations.api";
import { PricingForm } from "./PricingForm";
import { ExportDialog } from "./ExportDialog";
import { cylinders, customers, today } from "./market-options";
import "./competitor-pricing.css";

const money = (value: number) => formatCurrency(value);
const signed = (value: number) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${money(Math.abs(value))}`;
export function CompetitorPricingPage({ api = defaultApi, channel = "merchant", merchantId }: { api?: CompetitorPricingApi; channel?: "merchant" | "admin"; merchantId?: string } = {}) {
  const auth = useAuth();
  const toast = useToast();
  const client = useQueryClient();
  const scope = [channel, "competitor-pricing", merchantId ?? auth.user?.merchant?.id ?? auth.user?.user_id];
  const [filters, setFilters] = useState<MarketFilters>({ pincode: "", cylinderType: "LPG_19KG", customerType: customers[0].value });
  const pincode = useDebouncedValue(filters.pincode, 350);
  const params = { ...filters, pincode };
  const valid = /^[1-9]\d{5}$/.test(pincode) && pincode === filters.pincode;
  const [tab, setTab] = useState("overview");
  const [timeframe, setTimeframe] = useState<Timeframe>("30D");
  const [hiddenSeries, setHiddenSeries] = useState<string[]>([]);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState(today());
  const range = timeframe === "CUSTOM" ? { startDate, endDate } : {};
  const rangeValid = timeframe !== "CUSTOM" || Boolean(startDate && endDate && startDate <= endDate && endDate <= today() && (Date.parse(endDate) - Date.parse(startDate)) / 86400000 <= 365);
  const [exportOpen, setExportOpen] = useState(false);
  function presetRange(preset: string) {
    const end = today();
    const start = new Date(`${end}T00:00:00Z`);
    if (preset === "MTD") start.setUTCDate(1);
    else if (preset === "YTD") { start.setUTCMonth(0); start.setUTCDate(1); }
    else start.setUTCDate(start.getUTCDate() - Number(preset) + 1);
    setStartDate(start.toISOString().slice(0, 10)); setEndDate(end); setTimeframe("CUSTOM");
  }

  const [auditPincode, setAuditPincode] = useState("");
  const [auditCustomer, setAuditCustomer] = useState("");
  const [auditStart, setAuditStart] = useState("");
  const [auditEnd, setAuditEnd] = useState("");
  const [search, setSearch] = useState("");
  const searchTerm = useDebouncedValue(search, 300);
  const [auditCylinder, setAuditCylinder] = useState("");
  const [auditBrand, setAuditBrand] = useState("");
  const [offset, setOffset] = useState(0);
  const [dialog, setDialog] = useState<{ kind: "survey" | "benchmark" | "brand" | "depot" | "details"; row?: ComparisonRow; competitor?: Competitor } | null>(null);
  const [statusBrand, setStatusBrand] = useState<Competitor | null>(null);
  const canRecord = auth.can(PERMISSIONS.pricingManage) || auth.can(PERMISSIONS.competitorPricingRecord);
  const canManage = auth.can(PERMISSIONS.competitorPricingManage);

  const location = useQuery({ queryKey: [...scope, "location", pincode], queryFn: ({ signal }) => lookupPincode(pincode, merchantId, signal, channel), enabled: valid, retry: false });
  const brands = useQuery({ queryKey: [...scope, "brands"], queryFn: ({ signal }) => api.brands("", signal) });
  const directory = useQuery({ queryKey: [...scope, "directory", searchTerm], queryFn: ({ signal }) => api.brands(searchTerm, signal), enabled: tab === "brands" });
  const snapshot = useQuery({ queryKey: [...scope, "snapshot", params], queryFn: ({ signal }) => api.snapshot(params, signal), enabled: valid && (tab === "overview" || tab === "compare") });
  const comparison = useQuery({ queryKey: [...scope, "comparison", params], queryFn: ({ signal }) => api.comparison(params, signal), enabled: valid && (tab === "overview" || tab === "compare") });
  const history = useQuery({ queryKey: [...scope, "history", params, timeframe, range], queryFn: ({ signal }) => api.history({ ...params, timeframe, ...range }, signal), enabled: valid && rangeValid && tab === "trends" });
  const auditParams = { pincode: auditPincode || undefined, customerType: auditCustomer || undefined, startDate: auditStart || undefined, endDate: auditEnd || undefined, cylinderType: auditCylinder || undefined, competitorId: auditBrand || undefined, limit: 20, offset };
  const audit = useQuery({ queryKey: [...scope, "audit", auditParams], queryFn: ({ signal }) => api.audit(auditParams, signal), enabled: tab === "audit" && (!auditPincode || /^[1-9]\d{5}$/.test(auditPincode)) && (!auditStart || !auditEnd || auditStart <= auditEnd), retry: false });
  async function refresh() {
    await Promise.all([
      client.invalidateQueries({ queryKey: scope }),
      client.invalidateQueries({ queryKey: queryKeys.pricing.all })
    ]);
  }
  const toggleStatus = useMutation({ mutationFn: (brand: Competitor) => api.status(brand.id, brand.status === "ACTIVE" ? "INACTIVE" : "ACTIVE"), retry: false });
  const rows = comparison.data ?? [];
  const snap = snapshot.data;
  const needsMarket = tab === "overview" || tab === "compare" || tab === "trends";
  const series = [...new Set((history.data ?? []).flatMap(point => Object.keys(point).filter(key => key !== "date")))];
  const chartValues = (history.data ?? []).flatMap(point => Object.entries(point).filter(([key, value]) => key !== "date" && !hiddenSeries.includes(key) && typeof value === "number").map(([, value]) => Number(value)));
  const chartMin = chartValues.length ? Math.floor(Math.min(...chartValues) / 50) * 50 - 50 : 0;
  const chartMax = chartValues.length ? Math.ceil(Math.max(...chartValues) / 50) * 50 + 50 : 100;
  const chartTicks = Array.from({ length: 5 }, (_, index) => chartMin + (chartMax - chartMin) * index / 4);
  function seriesInfo(key: string) {
    const standard: Record<string, { name: string; color: string }> = { mbga: { name: "MBGA", color: "#2563EB" }, bharatGas: { name: "Bharat Gas", color: "#F97316" }, indane: { name: "Indane", color: "#EF4444" }, hpGas: { name: "HP Gas", color: "#10B981" } };
    return standard[key] ?? brands.data?.find(brand => brand.id === key) ?? { name: key, color: "#8B5CF6" };
  }

  const comparisonTable = <div className="market-table-wrap"><table className="market-table"><thead><tr><th>Brand</th><th>Quoted price</th><th>Gap vs MBGA</th><th>Survey details</th><th>Actions</th></tr></thead><tbody>{rows.map(row => <tr key={row.competitorId} className={row.isMbga ? "market-base" : undefined}>
    <td><span className="market-brand"><span className="market-dot" style={{ backgroundColor: row.color }} /><strong>{row.name}</strong></span>{row.isMbga && <small className="market-base-label">BASE BENCHMARK</small>}</td>
    <td><strong>{money(row.price)}</strong>{row.effectiveDate && <small>Effective {row.effectiveDate}</small>}</td>
    <td><span className={row.difference > 0 ? "market-higher" : row.difference < 0 ? "market-lower" : "text-muted"}>{signed(row.difference)} ({row.differencePercentage}%)</span></td>
    <td><span>{row.notes || "—"}</span><small>{row.updatedBy}{row.updatedByRole ? ` · ${row.updatedByRole}` : ""}</small><small>{formatDateTime(row.updatedAt)}</small></td>
    <td>{(!row.isMbga && canRecord) && <Button variant="secondary" size="sm" onClick={() => setDialog({ kind: row.isMbga ? "benchmark" : "survey", row })}>Edit rate</Button>}</td>
  </tr>)}</tbody></table></div>;

  const overview = <div className="stack">
    <InlineError error={snapshot.error || comparison.error} onRetry={() => void refresh()} />
    {valid && (snapshot.isLoading || comparison.isLoading) && <LoadingSkeleton />}
    {valid && snap && <div className="market-stats">
      <StatCard label="Your price · MBGA" value={money(snap.mbgaPrice)} icon="wallet" hint={cylinders.find(c => c.value === filters.cylinderType)?.label} />
      <StatCard label={rows.length === 1 ? "Market average · estimate" : "Market average"} value={money(snap.avgCompetitorPrice)} icon="chart" hint={`${Math.max(0, rows.length - 1)} active competitor quotes`} />
      <StatCard label="Your position" value={`${money(snap.difference)} ${snap.difference === 0 ? "same" : snap.isLower ? "lower" : "higher"}`} icon="trendingUp" hint={`${snap.differencePercentage}% gap vs market average`} tone={snap.difference === 0 ? "slate" : snap.isLower ? "green" : "red"} />
    </div>}
    {valid && rows.length === 1 && <Alert tone="info">No competitor quotes for this market yet. The market average is an estimate of MBGA + ₹75.</Alert>}
    {valid && rows.length > 0 && <Card title="Market comparison" subtitle="MBGA is the reference rate. Competitors are ordered from lowest to highest price." actions={<Button variant="ghost" onClick={() => setDialog({ kind: "details" })}>View details</Button>}>{comparisonTable}</Card>}
  </div>;
  const trends = <Card title="Price movements" subtitle="Daily observations; unknown prices remain blank." actions={<Select aria-label="History timeframe" value={timeframe} onChange={e => setTimeframe(e.target.value as Timeframe)} options={["7D", "30D", "3M", "1Y", "CUSTOM"].map(value => ({ value, label: value }))} />}>
    {timeframe === "CUSTOM" && <><div className="market-presets">{[{ value: "7", label: "Last 7 days" }, { value: "30", label: "Last 30 days" }, { value: "90", label: "Last 90 days" }, { value: "MTD", label: "Month to date" }, { value: "YTD", label: "Year to date" }].map(preset => <Button key={preset.value} size="sm" variant="secondary" onClick={() => presetRange(preset.value)}>{preset.label}</Button>)}</div><div className="market-filters"><Field label="History start date"><Input type="date" max={endDate || today()} value={startDate} onChange={e => setStartDate(e.target.value)} /></Field><Field label="History end date"><Input type="date" min={startDate} max={today()} value={endDate} onChange={e => setEndDate(e.target.value)} /></Field><Button variant="secondary" onClick={() => setTimeframe("30D")}>Reset to 30D</Button></div></>}
    {!rangeValid && <Alert tone="warning">Choose start and end dates, no later than today, within a 366-day period.</Alert>}
    <InlineError error={history.error} onRetry={() => void history.refetch()} />
    {valid && history.isLoading ? <LoadingSkeleton /> : valid && series.length ? <div className="market-chart" role="img" aria-label={`Competitor price movements over ${timeframe}`}><ResponsiveContainer width="100%" height={360}><LineChart data={history.data} margin={{ top: 15, right: 20, left: 15, bottom: 10 }}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="date" tickFormatter={value => String(value).slice(5)} minTickGap={35} /><YAxis domain={[chartMin, chartMax]} ticks={chartTicks} tickFormatter={value => `₹${value}`} /><Tooltip formatter={value => money(Number(value))} /><Legend onClick={entry => { const key = String(entry.dataKey); setHiddenSeries(previous => previous.includes(key) ? previous.filter(value => value !== key) : [...previous, key]); }} />{series.map(key => <Line key={key} dataKey={key} hide={hiddenSeries.includes(key)} name={seriesInfo(key).name} stroke={seriesInfo(key).color} strokeWidth={2} dot={false} connectNulls={false} type="stepAfter" />)}</LineChart></ResponsiveContainer></div> : valid && !history.error ? <EmptyState title="No price observations yet" description="Record a competitor quote to start tracking this market." /> : null}
  </Card>;
  const auditContent = <Card title="Recent price changes" subtitle="Filter recorded changes by market and India-time dates. Merchant-wide MBGA changes remain included.">
    <div className="market-filters"><Field label="Audit cylinder"><Select value={auditCylinder} onChange={e => { setAuditCylinder(e.target.value); setOffset(0); }} options={[{ value: "", label: "All cylinders" }, ...cylinders]} /></Field><Field label="Audit brand"><Select value={auditBrand} onChange={e => { setAuditBrand(e.target.value); setOffset(0); }} options={[{ value: "", label: "All brands" }, { value: "mbga_self", label: "MBGA" }, ...(brands.data ?? []).map(b => ({ value: b.id, label: b.name }))]} /></Field></div>
    <div className="market-filters"><Field label="Audit pincode" error={auditPincode && !/^[1-9]\d{5}$/.test(auditPincode) ? "Enter a valid pincode" : undefined}><Input inputMode="numeric" maxLength={6} value={auditPincode} onChange={e => { setAuditPincode(e.target.value.replace(/\D/g, "")); setOffset(0); }} /></Field><Field label="Audit segment"><Select options={[{ value: "", label: "All segments" }, ...customers]} value={auditCustomer} onChange={e => { setAuditCustomer(e.target.value); setOffset(0); }} /></Field><Field label="Audit start date"><Input type="date" max={auditEnd || today()} value={auditStart} onChange={e => { setAuditStart(e.target.value); setOffset(0); }} /></Field><Field label="Audit end date"><Input type="date" max={today()} min={auditStart} value={auditEnd} onChange={e => { setAuditEnd(e.target.value); setOffset(0); }} /></Field></div>
    {auditStart && auditEnd && auditStart > auditEnd && <Alert tone="warning">Audit start date must not exceed end date.</Alert>}
    <InlineError error={audit.error} />
    {audit.isLoading ? <LoadingSkeleton /> : !audit.error && !audit.data?.length ? <EmptyState title="No price changes" description="Price changes will appear here with staff attribution." /> : null}
    <div className="market-feed">{audit.data?.map(log => <article key={log.id} className="market-event"><span className="market-dot" style={{ backgroundColor: log.color }} /><div><strong>{log.competitorName} · {log.cylinderType}</strong><p>{money(log.oldPrice)} → {money(log.newPrice)} <span className={log.isIncrease ? "market-higher" : "market-lower"}>({signed(log.difference)})</span></p><small>{log.locationPincode || "All locations"} · {log.customerType || "All segments"}</small>{log.notes && <p>{log.notes}</p>}<small>{log.changedBy} · {log.changedByRole} · {formatDateTime(log.timestamp)}</small></div></article>)}</div>
    {!audit.error && <div className="market-pagination"><Button variant="secondary" disabled={offset === 0 || audit.isFetching} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous</Button><span>Page {offset / 20 + 1}</span><Button variant="secondary" disabled={(audit.data?.length ?? 0) < 20 || audit.isFetching} onClick={() => setOffset(offset + 20)}>Next</Button></div>}
  </Card>;
  const directoryContent = <Card title="Competitor directory" subtitle="Track national brands and local distributors." actions={canManage && <Button onClick={() => setDialog({ kind: "brand" })}>Add competitor</Button>}>
    <Field label="Search competitors"><Input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search by brand name or code" maxLength={160} /></Field>
    {search && <Button variant="ghost" size="sm" onClick={() => setSearch("")}>Clear search</Button>}
    <InlineError error={directory.error} onRetry={() => void directory.refetch()} />
    {directory.isLoading ? <LoadingSkeleton /> : !directory.error && !directory.data?.length ? <EmptyState title="No competitors found" description="Add your first competitor, or try another search." /> : null}
    <div className="market-directory">{directory.data?.map(brand => <article key={brand.id} className="market-brand-card"><span className="market-brand"><span className="market-dot" style={{ backgroundColor: brand.color }} /><strong>{brand.name}</strong></span><small>{brand.code} · {brand.status}</small><p>{brand.notes || "No notes added"}</p>{brand.depotAddress && <p>{[brand.depotAddress.line1, brand.depotAddress.city, brand.depotAddress.state, brand.depotAddress.pincode].filter(Boolean).join(", ")}{brand.depotAddress.latitude != null && <small>GPS: {brand.depotAddress.latitude}, {brand.depotAddress.longitude}</small>}</p>}<small>Updated {formatDateTime(brand.updatedAt)}</small>{canRecord && brand.status === "ACTIVE" && <Button size="sm" onClick={() => setDialog({ kind: "survey", competitor: brand })}>Record rate</Button>}{canManage && <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: "depot", competitor: brand })}>Edit depot</Button>}{canManage && <Button variant="secondary" size="sm" onClick={() => setStatusBrand(brand)}>{brand.status === "ACTIVE" ? "Inactivate" : "Activate"}</Button>}</article>)}</div>
  </Card>;

  return <div className="stack market-page">
    <PageHeader title="Competitor pricing" eyebrow="Market intelligence" description="Survey your market, compare cylinder rates, and keep a clear record of every change." actions={<><Button variant="secondary" onClick={() => void refresh()}>Refresh</Button><Button variant="secondary" disabled={!valid} onClick={() => setExportOpen(true)}>Export report</Button>{canRecord && <Button icon="plus" disabled={!valid || brands.isError || !brands.data?.some(b => b.status === "ACTIVE")} onClick={() => setDialog({ kind: "survey" })}>Record survey</Button>}</>} />
    {needsMarket && <Card><div className="market-filters"><Field label="Delivery pincode" hint="Enter the six-digit pincode to load this market." error={filters.pincode && !/^[1-9]\d{5}$/.test(filters.pincode) ? "Enter a valid six-digit pincode" : undefined}><Input inputMode="numeric" maxLength={6} value={filters.pincode} onChange={e => setFilters({ ...filters, pincode: e.target.value.replace(/\D/g, "") })} placeholder="e.g. 110001" /></Field><Field label="Customer segment"><Select options={customers} value={filters.customerType} onChange={e => setFilters({ ...filters, customerType: e.target.value })} /></Field><Field label="Cylinder size"><Select options={cylinders} value={filters.cylinderType} onChange={e => setFilters({ ...filters, cylinderType: e.target.value })} /></Field></div></Card>}
    {(snapshot.isFetching || comparison.isFetching || history.isFetching) && <p role="status" aria-live="polite">Updating market data…</p>}
    {valid && location.data && <Alert tone="info">Active hub: {pincode} · {location.data.offices[0]?.officeName} · {location.data.district}, {location.data.state}. Postal lookup does not confirm merchant delivery coverage.</Alert>}
    <InlineError error={location.error} />
    {filters.pincode && needsMarket && <Button variant="ghost" size="sm" onClick={() => setFilters({ ...filters, pincode: "" })}>Clear pincode</Button>}
    <InlineError error={brands.error} onRetry={() => void brands.refetch()} />
    {needsMarket && !valid && <Alert tone="info">Select a valid delivery pincode to view market prices and trends.</Alert>}
    <Tabs activeId={tab} onChange={setTab} label="Competitor pricing views" tabs={[{ id: "overview", label: "Overview", content: overview }, { id: "compare", label: "Compare", content: valid ? comparisonTable : null }, { id: "trends", label: "Trends", content: trends }, { id: "audit", label: "Recent changes", content: auditContent }, { id: "brands", label: "Competitors", content: directoryContent }]} />
    {dialog?.kind === "details" ? <Modal open title="Survey details" wide onClose={() => setDialog(null)}>{comparisonTable}</Modal> : dialog && <PricingForm key={`${dialog.kind}-${dialog.row?.competitorId ?? "new"}`} api={api} channel={channel} merchantId={merchantId} kind={dialog.kind} row={dialog.row} competitor={dialog.competitor} filters={params} brands={brands.data ?? []} onClose={() => setDialog(null)} onSaved={async () => { setDialog(null); toast.success("Pricing information saved"); await refresh(); }} />}
    {exportOpen && <ExportDialog api={api} filters={params} timeframe={timeframe} range={range} validRange={rangeValid} onClose={() => setExportOpen(false)} />}
    <ConfirmationDialog open={Boolean(statusBrand)} title={statusBrand?.status === "ACTIVE" ? "Inactivate competitor?" : "Activate competitor?"} description={statusBrand?.status === "ACTIVE" ? `${statusBrand.name} will be excluded from current comparisons. Existing history is retained.` : `Include ${statusBrand?.name ?? "this competitor"} in current comparisons again.`} confirmLabel={statusBrand?.status === "ACTIVE" ? "Inactivate" : "Activate"} onClose={() => setStatusBrand(null)} onConfirm={async () => { if (statusBrand) { await toggleStatus.mutateAsync(statusBrand); toast.success("Competitor status updated"); await refresh(); } }} />
  </div>;
}
