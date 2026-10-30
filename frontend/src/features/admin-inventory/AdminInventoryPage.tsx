import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { normalizeError } from "../../api/errors";
import {
  getInventory,
  updateReorderThreshold,
  listStockMovements,
  recordStockMovement,
  type RecordableMovementType,
  type RecordMovementInput,
  type StockBucket,
  type StockItem,
  type StockMovement,
  type StockMovementType
} from "../../api/inventory.api";
import { listMerchants } from "../../api/merchants.api";
import { queryKeys } from "../../api/query-keys";
import { useOptionalAuth } from "../../auth/auth-context";
import { Button, IconButton } from "../../components/common/Button";
import { Badge } from "../../components/common/StatusBadge";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert, EmptyState, ErrorState, InlineError, LoadingSkeleton, RefreshIndicator } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Input, Select, Textarea } from "../../components/forms/Field";
import { Card, PageHeader, StatCard } from "../../components/layout/Page";
import { DataTable, TableHeader, type Column } from "../../components/tables/DataTable";
import { useUrlFilters } from "../../hooks/useUrlFilters";
import { formatDateTime, formatNumber, formatRelativeTime } from "../../utils/format";
import type { Tone } from "../../utils/labels";

const FILTERS = ["merchant", "cylinder"] as const;
const MOVEMENT_LIMIT = 100;
const MAX_REORDER_LEVEL = 99_999;

const MOVEMENT_META: Record<StockMovementType, { label: string; tone: Tone }> = {
  RECEIVED_FILLED: { label: "Received filled", tone: "success" },
  SENT_TO_PLANT: { label: "Sent to plant", tone: "info" },
  MARKED_DAMAGED: { label: "Marked damaged", tone: "danger" },
  CORRECTION: { label: "Audit correction", tone: "warning" },
  DISPATCHED: { label: "Dispatched", tone: "accent" },
  EMPTIES_COLLECTED: { label: "Empties collected", tone: "neutral" }
};

const RECORDABLE: Array<{ value: RecordableMovementType; label: string; description: string }> = [
  { value: "RECEIVED_FILLED", label: "Received filled", description: "A refill load arrived from the plant. Adds to filled stock." },
  { value: "SENT_TO_PLANT", label: "Sent to plant", description: "Cylinders sent back to the plant: empties for refilling, or damaged ones for repair." },
  { value: "MARKED_DAMAGED", label: "Marked damaged", description: "Write cylinders off as damaged, from filled or empty stock." },
  { value: "CORRECTION", label: "Audit correction", description: "Set a bucket to the count found on a physical audit." }
];

const BUCKETS: Array<{ value: StockBucket; label: string }> = [
  { value: "filled", label: "Filled" },
  { value: "empty", label: "Empty" },
  { value: "damaged", label: "Damaged" }
];

function formatDeltas(deltas: StockMovement["deltas"]) {
  const parts = BUCKETS.flatMap(({ value, label }) => {
    const delta = deltas[value];
    return delta ? [`${delta > 0 ? "+" : "−"}${formatNumber(Math.abs(delta))} ${label.toLowerCase()}`] : [];
  });
  return parts.length ? parts.join(" · ") : "No change";
}

function newKey() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function AdminInventoryPage({
  merchantId: propMerchantId,
  isMerchantPanel = false,
  title = isMerchantPanel ? "Warehouse Inventory" : "Inventory"
}: {
  merchantId?: string;
  isMerchantPanel?: boolean;
  title?: string;
} = {}) {
  const auth = useOptionalAuth();
  const queryClient = useQueryClient();
  const toast = useToast();
  const canEditReorder = auth ? auth.can("inventory.adjust") : false;
  const { values, setFilter } = useUrlFilters(FILTERS);

  const merchantParams = { limit: 100, offset: 0 };
  const merchants = useQuery({
    queryKey: queryKeys.merchants.list(merchantParams),
    queryFn: ({ signal }) => listMerchants(merchantParams, signal),
    staleTime: 5 * 60_000
  });

  const currentMerchantId = (auth?.user?.merchant as any)?.id || merchants.data?.items[0]?.id || (isMerchantPanel ? "merch-current" : undefined);
  const merchantId = propMerchantId || (isMerchantPanel ? currentMerchantId : undefined) || values.merchant;
  const cylinder = values.cylinder || "ALL";
  const [recordFor, setRecordFor] = useState<string | null>(null);
  const [editingReorder, setEditingReorder] = useState<StockItem | null>(null);
  const [reorderValue, setReorderValue] = useState("");
  const [reorderError, setReorderError] = useState<string>();
  const reorderMutation = useMutation({
    mutationFn: ({item, value}: {item: StockItem; value: number}) => updateReorderThreshold(merchantId, item.cylinderType, value),
    onSuccess: () => {
      toast.success("Reorder level updated.");
      setEditingReorder(null);
      void queryClient.invalidateQueries({queryKey: queryKeys.inventory.all});
      void queryClient.invalidateQueries({queryKey: ["admin","dashboard"]});
      void queryClient.invalidateQueries({queryKey: ["admin","audit-logs"]});
    }
  });
  function saveReorder() {
    if (!editingReorder) return;
    const value=Number(reorderValue);
    if (!reorderValue.trim() || !Number.isSafeInteger(value) || value<0 || value>MAX_REORDER_LEVEL) {
      setReorderError(`Enter a whole number from 0 to ${formatNumber(MAX_REORDER_LEVEL)}.`);return;
    }
    setReorderError(undefined);
    reorderMutation.mutate({item:editingReorder,value});
  }

  // Stock is kept per merchant, so open on the first one rather than an empty screen.
  useEffect(() => {
    const first = merchants.data?.items[0];
    if (!merchantId && first && !isMerchantPanel) setFilter("merchant", first.id);
  }, [merchantId, merchants.data, setFilter, isMerchantPanel]);

  const snapshot = useQuery({
    queryKey: queryKeys.inventory.snapshot(merchantId),
    queryFn: ({ signal }) => getInventory(merchantId, signal),
    enabled: Boolean(merchantId)
  });

  const movementParams = { merchantId, cylinderType: cylinder, limit: MOVEMENT_LIMIT };
  const movements = useQuery({
    queryKey: queryKeys.inventory.movements(movementParams),
    queryFn: ({ signal }) => listStockMovements(movementParams, signal),
    enabled: Boolean(merchantId)
  });

  const items = useMemo(() => snapshot.data?.items ?? [], [snapshot.data]);
  const totals = useMemo(
    () =>
      items.reduce(
        (sum, item) => ({ filled: sum.filled + item.filled, empty: sum.empty + item.empty, damaged: sum.damaged + item.damaged }),
        { filled: 0, empty: 0, damaged: 0 }
      ),
    [items]
  );
  const lowStock = items.filter((item) => item.reorderThreshold > 0 && item.filled < item.reorderThreshold).length;

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.inventory.all });
  }

  const columns: Column<StockMovement>[] = [
    {
      key: "type",
      header: "Movement",
      primary: true,
      sortValue: (row) => row.type,
      render: (row) => {
        const meta = MOVEMENT_META[row.type] ?? { label: row.type, tone: "neutral" as Tone };
        return <Badge tone={meta.tone}>{meta.label}</Badge>;
      }
    },
    { key: "cylinder", header: "Cylinder", sortValue: (row) => row.cylinderLabel, render: (row) => <span className="nowrap">{row.cylinderLabel}</span> },
    { key: "qty", header: "Qty", align: "right", sortValue: (row) => row.quantity, render: (row) => <strong>{formatNumber(row.quantity)}</strong> },
    { key: "effect", header: "Effect on stock", render: (row) => <span className="nowrap">{formatDeltas(row.deltas)}</span> },
    {
      key: "note",
      header: "Note / reference",
      hideOnMobile: true,
      render: (row) => (
        <div className="cell-stack">
          <span style={{ display: "block", maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={row.note ?? undefined}>
            {row.note || "—"}
          </span>
          {row.referenceType ? (
            <small className="nowrap">
              {row.referenceType} {row.referenceId ?? ""}
            </small>
          ) : null}
        </div>
      )
    },
    {
      key: "recorded",
      header: "Recorded",
      sortValue: (row) => row.recordedAt,
      render: (row) => (
        <time dateTime={row.recordedAt} title={formatDateTime(row.recordedAt)} className="cell-stack">
          <span className="nowrap">{formatRelativeTime(row.recordedAt)}</span>
          <small className="nowrap">{row.recordedBy ?? "System"}</small>
        </time>
      )
    }
  ];

  return (
    <div className="page admin-inventory-page">
      <PageHeader
        title={title}
        documentTitle={title}
        description={isMerchantPanel ? "Live cylinder stock for your godown, with every movement that explains it." : "Live cylinder stock for each merchant's godown, with every movement that explains it."}
        meta={
          snapshot.data ? (
            <span className="text-muted text-small">
              As of {formatDateTime(snapshot.data.asOf)} <RefreshIndicator active={snapshot.isFetching} />
            </span>
          ) : null
        }
        actions={
          <>
            {!isMerchantPanel ? (
              <Field label="Merchant" hideLabel>
                <Select
                  value={merchantId}
                  onChange={(event) => setFilter("merchant", event.target.value)}
                  placeholder={merchants.isLoading ? "Loading merchants…" : "Select a merchant"}
                  disabled={merchants.isLoading}
                  options={(merchants.data?.items ?? []).map((merchant) => ({ value: merchant.id, label: merchant.business_name }))}
                />
              </Field>
            ) : null}
            <Button variant="secondary" icon="refresh" onClick={refresh} disabled={!merchantId || snapshot.isFetching}>
              Refresh
            </Button>
            <Button icon="plus" onClick={() => setRecordFor(items[0]?.cylinderType ?? "")} disabled={!merchantId || !items.length}>
              Record movement
            </Button>
          </>
        }
      />

      {merchants.error ? <InlineError error={merchants.error} title="Merchants could not be loaded" onRetry={() => void merchants.refetch()} /> : null}

      {!merchantId ? (
        merchants.isLoading ? (
          <LoadingSkeleton rows={4} label="Loading merchants" />
        ) : (
          <Card>
            <EmptyState icon="store" title="Choose a merchant" description="Stock is kept per godown. Pick a merchant above to see its inventory." />
          </Card>
        )
      ) : snapshot.isLoading ? (
        <LoadingSkeleton rows={6} label="Loading inventory" />
      ) : snapshot.error && !snapshot.data ? (
        <Card>
          <ErrorState error={snapshot.error} onRetry={() => void snapshot.refetch()} />
        </Card>
      ) : (
        <>
          <div className="kpi-grid" aria-label="Stock totals">
            <StatCard label="Filled cylinders" icon="box" tone="green" value={formatNumber(totals.filled)} hint="Ready to dispatch" />
            <StatCard label="Empty cylinders" icon="refresh" tone="blue" value={formatNumber(totals.empty)} hint="Awaiting refill at plant" />
            <StatCard label="Damaged" icon="ban" tone="red" value={formatNumber(totals.damaged)} hint="Written off, out of circulation" />
            <StatCard
              label="Low stock types"
              icon="warning"
              tone={lowStock ? "amber" : "slate"}
              value={formatNumber(lowStock)}
              hint="Filled below reorder level"
            />
          </div>

          {snapshot.data?.alerts.length ? (
            <div className="stack">
              {snapshot.data.alerts.map((alert) => (
                <Alert key={alert.id} tone={alert.severity === "CRITICAL" ? "error" : alert.severity === "WARNING" ? "warning" : "info"}>
                  {alert.message}
                </Alert>
              ))}
            </div>
          ) : null}

          <div className="grid-3" aria-label="Stock by cylinder type">
            {items.map((item) => (
              <StockCard key={item.cylinderType} item={item} onRecord={() => setRecordFor(item.cylinderType)}
                onEditReorder={canEditReorder ? () => {
                  reorderMutation.reset();setReorderError(undefined);setReorderValue(String(item.reorderThreshold));setEditingReorder(item);
                } : undefined} />
            ))}
          </div>

          <Card bodyless className="table-card">
            <TableHeader
              title="Movement history"
              count={movements.data?.length}
              description={`Newest first. Showing up to ${MOVEMENT_LIMIT} entries.`}
              actions={
                <Field label="Cylinder type" hideLabel>
                  <Select
                    value={cylinder === "ALL" ? "" : cylinder}
                    onChange={(event) => setFilter("cylinder", event.target.value)}
                    placeholder="All cylinder types"
                    options={items.map((item) => ({ value: item.cylinderType, label: item.cylinderLabel }))}
                  />
                </Field>
              }
            />
            <DataTable
              caption="Stock movement history"
              columns={columns}
              rows={movements.data}
              getRowKey={(row) => row.id}
              isLoading={movements.isLoading}
              error={movements.error}
              onRetry={() => void movements.refetch()}
              empty={<EmptyState icon="history" title="No movements yet" description="Refills, plant returns, damage and corrections will appear here." />}
            />
          </Card>
        </>
      )}

      <Modal open={Boolean(editingReorder)} title={`Edit reorder level${editingReorder ? ` · ${editingReorder.cylinderLabel}` : ""}`}
        onClose={()=>setEditingReorder(null)} busy={reorderMutation.isPending}
        footer={<><Button variant="secondary" disabled={reorderMutation.isPending} onClick={()=>setEditingReorder(null)}>Cancel</Button>
          <Button onClick={saveReorder} loading={reorderMutation.isPending} loadingText="Saving…">Save reorder level</Button></>}>
        <form className="stack" onSubmit={(event)=>{event.preventDefault();saveReorder();}}>
          <Field label="Reorder level (filled cylinders)" required error={reorderError} hint="Use 0 to disable reorder warnings for this cylinder type.">
            <Input type="number" min="0" max={MAX_REORDER_LEVEL} step="1" value={reorderValue} onChange={(event)=>setReorderValue(event.target.value)} autoFocus disabled={reorderMutation.isPending}/>
          </Field>
          {reorderMutation.error ? <Alert tone="error">{normalizeError(reorderMutation.error).userMessage}</Alert> : null}
        </form>
      </Modal>

      <RecordMovementDialog
        merchantId={merchantId}
        items={items}
        initialCylinder={recordFor}
        onClose={() => setRecordFor(null)}
        onRecorded={refresh}
      />
    </div>
  );
}

function StockCard({ item, onRecord, onEditReorder }: { item: StockItem; onRecord: () => void; onEditReorder?: () => void }) {
  const low = item.reorderThreshold > 0 && item.filled < item.reorderThreshold;
  const total = item.filled + item.empty + item.damaged;
  const pct = (value: number) => (total ? `${(value / total) * 100}%` : "0%");
  return (
    <Card
      title={item.cylinderLabel}
      subtitle={<span className="row" style={{gap:4}}>
        <span>Reorder at {formatNumber(item.reorderThreshold)} filled</span>
        {onEditReorder ? <IconButton icon="edit" label={`Edit reorder level for ${item.cylinderLabel}`} onClick={onEditReorder}/> : null}
      </span>}
      actions={low ? <Badge tone="danger">Low stock</Badge> : <Badge tone="success">Healthy</Badge>}
      footer={
        <div className="row-between">
          <span className="text-muted text-small">{item.updatedAt ? `Updated ${formatRelativeTime(item.updatedAt)}` : "No movements yet"}</span>
          <Button variant="link" size="sm" onClick={onRecord}>
            Record movement
          </Button>
        </div>
      }
    >
      <div className="stack">
        <div className="row-between">
          {[
            { label: "Filled", value: item.filled, color: "var(--green-500, #16a34a)" },
            { label: "Empty", value: item.empty, color: "var(--blue-500, #3b82f6)" },
            { label: "Damaged", value: item.damaged, color: "var(--red-500, #ef4444)" }
          ].map((bucket) => (
            <div key={bucket.label} className="cell-stack">
              <small className="text-muted">{bucket.label}</small>
              <strong style={{ fontSize: "1.5rem", color: bucket.label === "Filled" && low ? "var(--red-600, #dc2626)" : undefined }}>
                {formatNumber(bucket.value)}
              </strong>
            </div>
          ))}
        </div>
        <div
          aria-hidden="true"
          style={{ display: "flex", height: 8, borderRadius: 999, overflow: "hidden", background: "var(--border)" }}
          title={`${item.filled} filled · ${item.empty} empty · ${item.damaged} damaged`}
        >
          <span style={{ width: pct(item.filled), background: "var(--green-500, #16a34a)" }} />
          <span style={{ width: pct(item.empty), background: "var(--blue-500, #3b82f6)" }} />
          <span style={{ width: pct(item.damaged), background: "var(--red-500, #ef4444)" }} />
        </div>
      </div>
    </Card>
  );
}

type FormState = {
  type: RecordableMovementType;
  cylinderType: string;
  quantity: string;
  fromBucket: StockBucket;
  bucket: StockBucket;
  newCount: string;
  note: string;
  referenceId: string;
};

function RecordMovementDialog({
  merchantId,
  items,
  initialCylinder,
  onClose,
  onRecorded
}: {
  merchantId: string;
  items: StockItem[];
  /** null keeps the dialog closed. */
  initialCylinder: string | null;
  onClose: () => void;
  onRecorded: () => void;
}) {
  const toast = useToast();
  const open = initialCylinder !== null;
  const [form, setForm] = useState<FormState>(() => blank(initialCylinder ?? ""));
  const [submitted, setSubmitted] = useState(false);
  // One key per opening of the dialog, so a retry after a network error books the movement once.
  const [idempotencyKey, setIdempotencyKey] = useState(newKey);

  function blank(cylinderType: string): FormState {
    return { type: "RECEIVED_FILLED", cylinderType, quantity: "", fromBucket: "filled", bucket: "filled", newCount: "", note: "", referenceId: "" };
  }

  useEffect(() => {
    if (open) {
      setForm(blank(initialCylinder ?? ""));
      setSubmitted(false);
      setIdempotencyKey(newKey());
    }
  }, [open, initialCylinder]);

  const mutation = useMutation({
    mutationFn: (input: RecordMovementInput) => recordStockMovement(merchantId, input, idempotencyKey),
    onSuccess: (movement) => {
      toast.success(`${MOVEMENT_META[movement.type]?.label ?? "Movement"} recorded for ${movement.cylinderLabel}.`);
      onRecorded();
      onClose();
    }
  });

  const current = items.find((item) => item.cylinderType === form.cylinderType);
  const isCorrection = form.type === "CORRECTION";
  const quantity = Number.parseInt(form.quantity, 10);
  const newCount = Number.parseInt(form.newCount, 10);

  const errors = {
    cylinderType: form.cylinderType ? undefined : "Choose a cylinder type.",
    quantity: !isCorrection && !(quantity > 0) ? "Enter a quantity of at least 1." : undefined,
    newCount: isCorrection && !(newCount >= 0) ? "Enter the counted number (0 or more)." : undefined,
    note: isCorrection && !form.note.trim() ? "Say why the count is being corrected." : undefined
  };
  const valid = !Object.values(errors).some(Boolean);

  // Show what the movement will do before it is booked.
  const preview = (() => {
    if (!current) return null;
    if (isCorrection) {
      if (!(newCount >= 0)) return null;
      return `${BUCKETS.find((b) => b.value === form.bucket)?.label} goes from ${current[form.bucket]} to ${newCount}.`;
    }
    if (!(quantity > 0)) return null;
    if (form.type === "RECEIVED_FILLED") return `Filled goes from ${current.filled} to ${current.filled + quantity}.`;
    const fromLabel = BUCKETS.find((b) => b.value === form.fromBucket)?.label ?? form.fromBucket;
    if (form.type === "SENT_TO_PLANT") return `${fromLabel} goes from ${current[form.fromBucket]} to ${current[form.fromBucket] - quantity}.`;
    return `${fromLabel} goes from ${current[form.fromBucket]} to ${current[form.fromBucket] - quantity}; damaged goes to ${current.damaged + quantity}.`;
  })();
  const goesNegative = Boolean(
    current &&
      !isCorrection &&
      quantity > 0 &&
      (form.type === "SENT_TO_PLANT" || form.type === "MARKED_DAMAGED") &&
      quantity > current[form.fromBucket]
  );

  function submit() {
    setSubmitted(true);
    if (!valid || goesNegative) return;
    const input: RecordMovementInput = {
      type: form.type,
      cylinderType: form.cylinderType,
      note: form.note.trim() || undefined,
      referenceId: form.referenceId.trim() || undefined
    };
    if (isCorrection) {
      input.bucket = form.bucket;
      input.newCount = newCount;
    } else {
      input.quantity = quantity;
      // Both take cylinders out of a bucket, and the backend needs to know which one.
      if (form.type === "SENT_TO_PLANT" || form.type === "MARKED_DAMAGED") input.fromBucket = form.fromBucket;
    }
    mutation.mutate(input);
  }

  const set = <K extends keyof FormState>(key: K) => (event: { target: { value: string } }) =>
    setForm((previous) => ({ ...previous, [key]: event.target.value as FormState[K] }));

  return (
    <Modal
      open={open}
      title="Record stock movement"
      description={RECORDABLE.find((option) => option.value === form.type)?.description}
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
          <Button icon="check" onClick={submit} loading={mutation.isPending} loadingText="Recording…">
            Record movement
          </Button>
        </>
      }
    >
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <div className="grid-2">
          <Field label="Movement type" required>
            <Select
              value={form.type}
              onChange={(event) => {
                const type = event.target.value as RecordableMovementType;
                // Each type starts from the bucket it usually takes from.
                setForm((previous) => ({ ...previous, type, fromBucket: type === "SENT_TO_PLANT" ? "empty" : "filled" }));
              }}
              options={RECORDABLE.map(({ value, label }) => ({ value, label }))}
            />
          </Field>
          <Field label="Cylinder type" required error={submitted ? errors.cylinderType : undefined}>
            <Select
              value={form.cylinderType}
              onChange={set("cylinderType")}
              placeholder="Choose…"
              options={items.map((item) => ({ value: item.cylinderType, label: item.cylinderLabel }))}
            />
          </Field>
        </div>

        {isCorrection ? (
          <div className="grid-2">
            <Field label="Bucket" required>
              <Select value={form.bucket} onChange={set("bucket")} options={BUCKETS} />
            </Field>
            <Field label="Counted number" required error={submitted ? errors.newCount : undefined} hint={current ? `Currently ${current[form.bucket]}` : undefined}>
              <Input type="number" min={0} inputMode="numeric" value={form.newCount} onChange={set("newCount")} />
            </Field>
          </div>
        ) : (
          <div className="grid-2">
            <Field label="Quantity" required error={submitted ? errors.quantity : undefined}>
              <Input type="number" min={1} inputMode="numeric" value={form.quantity} onChange={set("quantity")} autoFocus />
            </Field>
            {form.type === "MARKED_DAMAGED" ? (
              <Field label="Taken from" required>
                <Select value={form.fromBucket} onChange={set("fromBucket")} options={BUCKETS.filter((b) => b.value !== "damaged")} />
              </Field>
            ) : form.type === "SENT_TO_PLANT" ? (
              <Field label="Sent from" required hint={current ? `${current[form.fromBucket]} in this bucket now` : undefined}>
                <Select value={form.fromBucket} onChange={set("fromBucket")} options={BUCKETS.filter((b) => b.value !== "filled")} />
              </Field>
            ) : (
              <Field label="Challan / reference" optional>
                <Input value={form.referenceId} onChange={set("referenceId")} maxLength={60} />
              </Field>
            )}
          </div>
        )}

        {form.type === "SENT_TO_PLANT" ? (
          <Field label="Challan / reference" optional>
            <Input value={form.referenceId} onChange={set("referenceId")} maxLength={60} />
          </Field>
        ) : null}

        <Field label="Note" required={isCorrection} optional={!isCorrection} error={submitted ? errors.note : undefined}>
          <Textarea value={form.note} onChange={set("note")} rows={2} maxLength={500} />
        </Field>

        {goesNegative ? (
          <Alert tone="warning">That is more than is in stock. Record a correction first if the count is wrong.</Alert>
        ) : preview ? (
          <Alert tone="info">{preview}</Alert>
        ) : null}
        {mutation.error ? <MovementError error={mutation.error} /> : null}
      </form>
    </Modal>
  );
}

/** Names the field the backend rejected, rather than showing a bare "Required". */
function MovementError({ error }: { error: unknown }) {
  const normalized = normalizeError(error);
  const fields = Object.entries(normalized.fieldErrors ?? {});
  const label = (field: string) =>
    ({ fromBucket: "Taken from", bucket: "Bucket", newCount: "Counted number", quantity: "Quantity", cylinderType: "Cylinder type", note: "Note" })[field] ?? field;
  return (
    <Alert tone="error" title={fields.length ? "The movement was not recorded" : undefined}>
      {fields.length ? (
        <ul style={{ margin: 0, paddingLeft: "1.2em" }}>
          {fields.map(([field, message]) => (
            <li key={field}>
              <strong>{label(field)}</strong>: {message}
            </li>
          ))}
        </ul>
      ) : (
        normalized.userMessage
      )}
    </Alert>
  );
}

export default AdminInventoryPage;
