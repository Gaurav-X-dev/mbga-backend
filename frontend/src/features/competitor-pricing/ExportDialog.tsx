import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { competitorPricingApi as defaultApi, type CompetitorPricingApi, type ExportOptions, type MarketFilters, type Timeframe, type DateRange } from "../../api/competitor-pricing.api";
import { Button } from "../../components/common/Button";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert, InlineError } from "../../components/feedback/Feedback";
import { Field, Select } from "../../components/forms/Field";

export function ExportDialog({ api = defaultApi, filters, timeframe, range, validRange, onClose }: { api?: CompetitorPricingApi; filters: MarketFilters; timeframe: Timeframe; range: DateRange; validRange: boolean; onClose: () => void }) {
  const [format, setFormat] = useState<ExportOptions["format"]>("XLSX");
  const [dataset, setDataset] = useState<ExportOptions["dataset"]>("comparison");
  const [includeAudit, setIncludeAudit] = useState(false);
  const mutation = useMutation({ mutationFn: () => api.exportReport({ ...filters, timeframe, ...range, format, dataset, includeAudit }), retry: false });
  return <Modal open title="Export pricing report" onClose={onClose} busy={mutation.isPending} footer={<><Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>Cancel</Button><Button disabled={!validRange} loading={mutation.isPending} onClick={() => { void mutation.mutateAsync().then(onClose).catch(() => undefined); }}>Download report</Button></>}>
    <div className="stack"><p>{filters.pincode} · {filters.customerType} · {filters.cylinderType} · {timeframe}{range.startDate ? ` (${range.startDate} to ${range.endDate})` : ""}</p>
      <Field label="Export format"><Select options={[{ value: "XLSX", label: "Excel workbook (.xlsx)" }, { value: "CSV", label: "CSV table (.csv)" }]} value={format} onChange={e => setFormat(e.target.value as ExportOptions["format"])} /></Field>
      {format === "CSV" ? <Field label="CSV dataset"><Select value={dataset} onChange={e => setDataset(e.target.value as ExportOptions["dataset"])} options={[{ value: "snapshot", label: "Market snapshot" }, { value: "comparison", label: "Price comparison" }, { value: "history", label: "Price history" }, { value: "audit", label: "Audit feed (office staff only)" }]} /></Field> : <><p>Includes separate Market Snapshot, Price Comparison, and Price History sheets.</p><label className="market-checkbox"><input type="checkbox" checked={includeAudit} onChange={e => setIncludeAudit(e.target.checked)} /> Include complete filtered audit feed (office staff only)</label></>}
      <Alert tone="info">Snapshot and comparison show current rates. History uses the selected period. Audit dates filter when changes were recorded in India time; merchant-wide MBGA changes are included. Export includes all matching audit pages, up to 10,000 events.</Alert>
      {!validRange && <Alert tone="warning">Select a valid custom range of at most 366 days before exporting.</Alert>}
      <InlineError error={mutation.error} />
    </div>
  </Modal>;
}
