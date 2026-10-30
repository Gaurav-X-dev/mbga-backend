import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { normalizeError } from "../../api/errors";
import { listMerchants } from "../../api/merchants.api";
import { queryKeys } from "../../api/query-keys";
import { useOptionalAuth } from "../../auth/auth-context";
import { createVehicle, getVehiclePincodes, listVehicles, updateVehicle, type Vehicle } from "../../api/vehicles.api";
import { Button } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { Badge } from "../../components/common/StatusBadge";
import { ConfirmationDialog, Modal } from "../../components/feedback/Dialogs";
import { Alert, EmptyState, InlineError, LoadingSkeleton, RefreshIndicator } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Input, SearchInput, Select, Textarea } from "../../components/forms/Field";
import { Card, PageHeader, StatCard } from "../../components/layout/Page";
import { DataTable, FilterBar, TableHeader, type Column } from "../../components/tables/DataTable";
import { useSearchFilter, useUrlFilters } from "../../hooks/useUrlFilters";
import { formatDate, formatNumber, formatRelativeTime } from "../../utils/format";
import { PostalImportButton } from "./PostalImportButton";
import { VehiclePincodesDialog } from "./VehiclePincodesDialog";

const FILTERS = ["merchant", "show", "search"] as const;

const TABS = [
  { value: "", label: "In service" },
  { value: "retired", label: "Retired" },
  { value: "all", label: "All Fleet" }
];

export const VEHICLE_TYPES = [
  { label: "Mini Truck", value: "Mini Truck" },
  { label: "Medium Truck", value: "Truck (Medium)" },
  { label: "Heavy Truck", value: "Truck (Heavy)" },
  { label: "Pickup Van", value: "Pickup Van" },
  { label: "Auto Three-Wheeler", value: "Auto Three-Wheeler" },
  { label: "Other", value: "Other" }
];

export const INDIAN_VEHICLE_PATTERNS = {
  STANDARD_RTO: /^[A-Z]{2}[0-9]{2}[A-HJ-NP-Z]{1,2}[0-9]{4}$/,
  BHARAT_SERIES: /^[0-9]{2}BH[0-9]{4}[A-HJ-NP-Z]{1,2}$/,
  FLEXIBLE_STANDARD: /^[A-Z]{2}[\ -]{0,1}[0-9]{2}[\ -]{0,1}[A-HJ-NP-Z]{1,2}[\ -]{0,1}[0-9]{4}$/,
  FLEXIBLE_BHARAT: /^[0-9]{2}[\ -]{0,1}BH[\ -]{0,1}[0-9]{4}[\ -]{0,1}[A-HJ-NP-Z]{1,2}$/
} as const;

export function validateVehicleNumber(value: string): string | undefined {
  if (!value || !value.trim()) return "Vehicle registration number is required";
  const clean = value.trim().toUpperCase();
  const unspaced = clean.replace(/[\s-]/g, "");
  const isValid =
    INDIAN_VEHICLE_PATTERNS.STANDARD_RTO.test(unspaced) ||
    INDIAN_VEHICLE_PATTERNS.BHARAT_SERIES.test(unspaced) ||
    INDIAN_VEHICLE_PATTERNS.FLEXIBLE_STANDARD.test(clean) ||
    INDIAN_VEHICLE_PATTERNS.FLEXIBLE_BHARAT.test(clean);

  if (!isValid) {
    return "Enter a valid vehicle number (e.g. MH 03 C 3843, RJ00XX0000, or 22BH1234AB)";
  }
  return undefined;
}

/** Parses stored label into vehicle type and capacity. */
function parseLabel(label?: string | null): { vehicleType: string; capacityKg: string } {
  if (!label) return { vehicleType: "Mini Truck", capacityKg: "" };
  const parts = label.split("•").map((s) => s.trim());
  const typePart = parts[0] || "Mini Truck";
  const matchedType = VEHICLE_TYPES.some((t) => t.value === typePart) ? typePart : "Other";
  const capPart = parts[1] || "";
  const match = capPart.match(/(\d+)/);
  return {
    vehicleType: matchedType,
    capacityKg: match ? match[1] : ""
  };
}

/** Normalisation matching backend. */
function normaliseNumber(value: string) {
  return value.toUpperCase().replace(/[^A-Z0-9]/g, "");
}

export function AdminVehiclesPage({
  merchantId: propMerchantId,
  isMerchantPanel = false,
  title = "Fleet Vehicles"
}: {
  merchantId?: string;
  isMerchantPanel?: boolean;
  title?: string;
} = {}) {
  const auth = useOptionalAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { values, setFilter } = useUrlFilters(FILTERS);
  const [searchText, setSearchText] = useSearchFilter(values.search, (value) => setFilter("search", value));

  const merchantParams = { limit: 100, offset: 0 };
  const merchants = useQuery({
    queryKey: queryKeys.merchants.list(merchantParams),
    queryFn: ({ signal }) => listMerchants(merchantParams, signal),
    staleTime: 5 * 60_000
  });

  const currentMerchantId = (auth?.user?.merchant as any)?.id || merchants.data?.items[0]?.id || (isMerchantPanel ? "merch-current" : undefined);
  const merchantId = propMerchantId || (isMerchantPanel ? currentMerchantId : undefined) || values.merchant;
  const show = values.show;
  const [editing, setEditing] = useState<Vehicle | "new" | null>(null);
  const [toggling, setToggling] = useState<Vehicle | null>(null);
  const [mapping, setMapping] = useState<Vehicle | null>(null);

  // Vans belong to a merchant, so open on the first one rather than an empty screen.
  useEffect(() => {
    const first = merchants.data?.items[0];
    if (!merchantId && first && !isMerchantPanel) setFilter("merchant", first.id);
  }, [merchantId, merchants.data, setFilter, isMerchantPanel]);

  // Fetch full fleet for merchant
  const params = { merchantId };
  const query = useQuery({
    queryKey: queryKeys.vehicles.list(params),
    queryFn: ({ signal }) => listVehicles(params, signal),
    enabled: Boolean(merchantId),
    placeholderData: keepPreviousData
  });

  const allVehicles = query.data?.items ?? [];

  // Pincode matching state when searching by a 6-digit numeric pincode (matching merchant app)
  const [matchedPincodeVehicleIds, setMatchedPincodeVehicleIds] = useState<Set<string> | null>(null);

  useEffect(() => {
    const q = (searchText || "").trim();
    if (!merchantId) return;

    if (/^\d{6}$/.test(q)) {
      let cancelled = false;
      const fetchPincodesForSearch = async () => {
        const matched = new Set<string>();
        await Promise.all(
          allVehicles.map(async (v) => {
            try {
              let pins = queryClient.getQueryData<{ pincodes: string[] }>(queryKeys.vehicles.pincodes(merchantId, v.id))?.pincodes;
              if (!pins) {
                const res = await queryClient.fetchQuery({
                  queryKey: queryKeys.vehicles.pincodes(merchantId, v.id),
                  queryFn: () => getVehiclePincodes(merchantId, v.id),
                  staleTime: 5 * 60 * 1000
                });
                pins = res.pincodes;
              }
              if (pins && pins.includes(q)) {
                matched.add(v.id);
              }
            } catch {
              // Ignore failure for individual lookup
            }
          })
        );
        if (!cancelled) {
          setMatchedPincodeVehicleIds(matched);
        }
      };

      void fetchPincodesForSearch();
      return () => {
        cancelled = true;
      };
    } else {
      setMatchedPincodeVehicleIds(null);
    }
  }, [searchText, allVehicles, queryClient, merchantId]);

  // Filter vehicles matching search (registration number, label, notes, OR 6-digit mapped pincode)
  const filteredVehicles = allVehicles.filter((v) => {
    const q = (searchText || "").trim().toLowerCase();
    if (!q) return true;

    // Six-digit numeric pincode search matching merchant app
    if (/^\d{6}$/.test(q)) {
      if (v.number.toLowerCase().includes(q)) return true;
      const cachedPins = queryClient.getQueryData<{ pincodes: string[] }>(queryKeys.vehicles.pincodes(merchantId, v.id))?.pincodes;
      if (cachedPins && cachedPins.includes(q)) return true;
      if (matchedPincodeVehicleIds && matchedPincodeVehicleIds.has(v.id)) return true;
      return false;
    }

    // Standard text search: number, label, or notes
    return (
      v.number.toLowerCase().includes(q) ||
      (v.label ?? "").toLowerCase().includes(q) ||
      (v.notes ?? "").toLowerCase().includes(q)
    );
  });

  const active = filteredVehicles.filter((v) => v.isActive);
  const retired = filteredVehicles.filter((v) => !v.isActive);
  const rows = show === "retired" ? retired : show === "all" ? filteredVehicles : active;

  const totalActive = allVehicles.filter((v) => v.isActive).length;
  const totalRetired = allVehicles.filter((v) => !v.isActive).length;

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.vehicles.all });
  }

  const columns: Column<Vehicle>[] = [
    {
      key: "number",
      header: "Vehicle",
      primary: true,
      sortValue: (v) => v.number,
      render: (v) => (
        <div className="cell-stack">
          <button type="button" className="btn--link cell-primary__title mono nowrap" onClick={() => setEditing(v)}>
            {v.number}
          </button>
          {v.label ? <small className="nowrap">{v.label}</small> : null}
        </div>
      )
    },
    {
      key: "pincodes",
      header: "Mapped Pincodes",
      render: (v) => (
        <VehiclePincodesCell
          merchantId={merchantId}
          vehicle={v}
          onManage={() => setMapping(v)}
        />
      )
    },
    {
      key: "notes",
      header: "Notes",
      render: (v) => (
        <span
          title={v.notes ?? undefined}
          className={v.notes ? undefined : "text-muted"}
          style={{ display: "block", maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
        >
          {v.notes || "—"}
        </span>
      )
    },
    {
      key: "added",
      header: "Added",
      sortValue: (v) => v.createdAt,
      render: (v) => (
        <div className="cell-stack">
          <span className="nowrap">{formatDate(v.createdAt)}</span>
          <small className="nowrap">{formatRelativeTime(v.createdAt)}</small>
        </div>
      )
    },
    {
      key: "status",
      header: "Status",
      sortValue: (v) => (v.isActive ? 0 : 1),
      render: (v) => (v.isActive ? <Badge tone="success">In service</Badge> : <Badge tone="neutral">Retired</Badge>)
    }
  ];

  return (
    <div className="page admin-vehicles-page">
      <PageHeader
        title={title}
        documentTitle={title}
        description={isMerchantPanel ? "Register and manage agency fleet vehicles, capacity, and mapped delivery pincodes." : "Register and manage fleet vehicles, capacity, and mapped delivery pincodes matching the merchant app."}
        meta={<RefreshIndicator active={query.isFetching && !query.isLoading} />}
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
            <PostalImportButton />
            <Button icon="plus" onClick={() => setEditing("new")} disabled={!merchantId}>
              Add vehicle
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
            <EmptyState icon="store" title="Choose a merchant" description="Fleet vehicles belong to a merchant. Pick one above." />
          </Card>
        )
      ) : (
        <>
          <div className="kpi-grid" aria-label="Fleet summary">
            <StatCard label="In service" icon="truck" tone="green" value={query.data ? formatNumber(totalActive) : "—"} hint="Can be assigned a round" />
            <StatCard label="Retired" icon="ban" tone="slate" value={query.data ? formatNumber(totalRetired) : "—"} hint="Kept so old slips still read" />
            <StatCard label="Total fleet" icon="box" tone="blue" value={query.data ? formatNumber(allVehicles.length) : "—"} hint="Every van on record" />
          </div>

          <Card bodyless className="table-card">
            <div className="status-tabs status-tabs--card" role="tablist" aria-label="Vehicle status">
              {TABS.map((tab) => (
                <button key={tab.label} type="button" role="tab" aria-selected={show === tab.value} onClick={() => setFilter("show", tab.value)}>
                  {tab.label}
                  <span className="tab-count">{tab.value === "retired" ? retired.length : tab.value === "all" ? filteredVehicles.length : active.length}</span>
                </button>
              ))}
            </div>
            <TableHeader title={TABS.find((t) => t.value === show)?.label ?? "Fleet Vehicles"} count={rows.length} description="Newest first. Select a vehicle or manage mapped pincodes." />
            <FilterBar onReset={() => setFilter("search", "")} canReset={Boolean(values.search)}>
              <SearchInput
                label="Search vehicles"
                placeholder="Search registration or pincode..."
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
              />
            </FilterBar>

            {query.error && query.data ? (
              <div style={{ padding: "var(--space-4)" }}>
                <InlineError error={query.error} title="The list could not be refreshed" onRetry={() => void query.refetch()} />
              </div>
            ) : null}

            <DataTable
              caption="Vehicles"
              columns={columns}
              rows={query.data ? rows : undefined}
              getRowKey={(v) => v.id}
              onRowClick={(v) => setEditing(v)}
              rowLabel={(v) => v.number}
              rowActions={(v) => [
                { label: "Edit details", icon: "edit", onSelect: () => setEditing(v) },
                { label: "Manage pincodes", icon: "mapPin", onSelect: () => setMapping(v) },
                v.isActive
                  ? { label: "Retire vehicle", icon: "ban", danger: true, onSelect: () => setToggling(v) }
                  : { label: "Put back in service", icon: "refresh", onSelect: () => setToggling(v) }
              ]}
              isLoading={query.isLoading}
              error={query.data ? undefined : query.error}
              onRetry={() => void query.refetch()}
              empty={
                values.search ? (
                  <EmptyState icon="search" title="No vehicles match" description="Try a different registration number or 6-digit pincode." />
                ) : show === "retired" ? (
                  <EmptyState icon="truck" title="No retired vehicles" description="Vehicles taken off the road appear here." />
                ) : (
                  <EmptyState
                    icon="truck"
                    title="No vehicles yet"
                    description="Add vehicles to assign to delivery trips and map to servicing pincodes."
                    action={<Button icon="plus" onClick={() => setEditing("new")}>Add vehicle</Button>}
                  />
                )
              }
            />
          </Card>
        </>
      )}

      {merchantId ? (
        <VehicleDialog
          merchantId={merchantId}
          vehicle={editing}
          onClose={() => setEditing(null)}
          onSaved={(saved, created) => {
            toast.success(created ? `Vehicle ${saved.number} created successfully.` : `Vehicle ${saved.number} updated.`);
            invalidate();
          }}
        />
      ) : null}

      {merchantId ? <VehiclePincodesDialog merchantId={merchantId} vehicle={mapping} onClose={() => setMapping(null)} /> : null}

      <ConfirmationDialog
        open={toggling !== null}
        title={toggling?.isActive ? `Retire ${toggling.number}?` : `Put ${toggling?.number ?? "this vehicle"} back in service?`}
        description={
          toggling?.isActive
            ? "It will no longer be offered when assigning trips. Completed delivery slips keep naming it, and it can be reactivated anytime."
            : "It will become available again for round and delivery assignments."
        }
        confirmLabel={toggling?.isActive ? "Retire" : "Put back in service"}
        confirmVariant={toggling?.isActive ? "danger" : "primary"}
        onClose={() => setToggling(null)}
        onConfirm={async () => {
          if (!toggling) return;
          const saved = await updateVehicle(merchantId, toggling.id, { isActive: !toggling.isActive });
          toast.success(saved.isActive ? `${saved.number} marked as active.` : `${saved.number} marked as inactive.`);
          invalidate();
        }}
      />
    </div>
  );
}

/** Displays mapped pincodes directly inside the table row with interactive chips. */
function VehiclePincodesCell({
  merchantId,
  vehicle,
  onManage
}: {
  merchantId: string;
  vehicle: Vehicle;
  onManage: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const query = useQuery({
    queryKey: queryKeys.vehicles.pincodes(merchantId, vehicle.id),
    queryFn: ({ signal }) => getVehiclePincodes(merchantId, vehicle.id, signal),
    staleTime: 5 * 60_000
  });

  const pincodes = query.data?.pincodes ?? [];
  const DEFAULT_VISIBLE = 3;
  const visiblePincodes = expanded ? pincodes : pincodes.slice(0, DEFAULT_VISIBLE);
  const remaining = pincodes.length - DEFAULT_VISIBLE;

  if (query.isLoading) {
    return <span className="text-muted text-small">Loading pincodes…</span>;
  }

  if (pincodes.length === 0) {
    return (
      <div className="row" style={{ gap: 6, alignItems: "center" }} onClick={(e) => e.stopPropagation()}>
        <span className="text-muted text-small">No pincodes mapped</span>
        <button
          type="button"
          className="btn--link text-small"
          onClick={onManage}
          style={{ fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 3 }}
        >
          <Icon name="plus" size={12} />
          Map Pincodes
        </button>
      </div>
    );
  }

  return (
    <div className="vehicle-pincodes-grid" onClick={(e) => e.stopPropagation()}>
      {visiblePincodes.map((pin) => (
        <span key={pin} className="vehicle-pincode-chip" title={`Served pincode: ${pin}`}>
          <Icon name="mapPin" size={11} />
          {pin}
        </span>
      ))}
      {remaining > 0 && !expanded && (
        <button
          type="button"
          className="vehicle-pincode-chip--more"
          onClick={() => setExpanded(true)}
          title={`Show all ${pincodes.length} mapped pincodes`}
        >
          +{remaining} more
        </button>
      )}
      {expanded && pincodes.length > DEFAULT_VISIBLE && (
        <button
          type="button"
          className="vehicle-pincode-chip--more"
          onClick={() => setExpanded(false)}
        >
          Show less
        </button>
      )}
    </div>
  );
}

function VehicleDialog({
  merchantId,
  vehicle,
  onClose,
  onSaved
}: {
  merchantId: string;
  vehicle: Vehicle | "new" | null;
  onClose: () => void;
  onSaved: (vehicle: Vehicle, created: boolean) => void;
}) {
  const existing = vehicle && vehicle !== "new" ? vehicle : null;
  const [number, setNumber] = useState("");
  const [vehicleType, setVehicleType] = useState("Mini Truck");
  const [capacityKg, setCapacityKg] = useState("");
  const [notes, setNotes] = useState("");
  const [numberError, setNumberError] = useState<string | undefined>(undefined);
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (vehicle === null) return;
    setSubmitted(false);
    setNumberError(undefined);
    if (existing) {
      setNumber(existing.number);
      const parsed = parseLabel(existing.label);
      setVehicleType(parsed.vehicleType);
      setCapacityKg(parsed.capacityKg);
      setNotes(existing.notes ?? "");
    } else {
      setNumber("");
      setVehicleType("Mini Truck");
      setCapacityKg("");
      setNotes("");
    }
  }, [vehicle, existing]);

  const mutation = useMutation({
    mutationFn: async () => {
      const cleanNumber = number.trim().toUpperCase();
      const capNum = capacityKg.trim() ? parseInt(capacityKg.trim(), 10) : undefined;
      const computedLabel = [
        vehicleType,
        capNum && !isNaN(capNum) ? `${capNum} kg` : null
      ]
        .filter(Boolean)
        .join(" • ");

      if (!existing) {
        return createVehicle(merchantId, {
          number: cleanNumber,
          label: computedLabel || undefined,
          notes: notes.trim() || undefined
        });
      }

      return updateVehicle(merchantId, existing.id, {
        ...(cleanNumber !== existing.number ? { number: cleanNumber } : {}),
        ...(computedLabel !== (existing.label ?? "") ? { label: computedLabel || null } : {}),
        ...(notes.trim() !== (existing.notes ?? "") ? { notes: notes.trim() || null } : {})
      });
    },
    onSuccess: (saved) => {
      onSaved(saved, !existing);
      onClose();
    }
  });

  const normalised = normaliseNumber(number);
  const validationErr = validateVehicleNumber(number);
  const error = mutation.error ? normalizeError(mutation.error) : null;

  function handleNumberChange(val: string) {
    const uppercased = val.toUpperCase();
    setNumber(uppercased);
    if (submitted) {
      setNumberError(validateVehicleNumber(uppercased));
    }
  }

  function submit() {
    setSubmitted(true);
    const err = validateVehicleNumber(number);
    setNumberError(err);
    if (!err) {
      mutation.mutate();
    }
  }

  return (
    <Modal
      open={vehicle !== null}
      title={existing ? `Edit ${existing.number}` : "Add Fleet Vehicle"}
      description={existing ? undefined : "Register a new vehicle for delivery assignments matching the merchant app."}
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
          <Button icon="check" onClick={submit} loading={mutation.isPending} loadingText="Saving…">
            {existing ? "Save changes" : "Add vehicle"}
          </Button>
        </>
      }
    >
      <form
        className="stack"
        style={{ gap: 14 }}
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        {existing && !existing.isActive ? (
          <Alert tone="info">This vehicle is retired. Use “Put back in service” from the list to assign it again.</Alert>
        ) : null}

        {/* Live Preview Header Card */}
        <div
          style={{
            padding: "10px 14px",
            background: "var(--surface-muted, #f8fafc)",
            borderRadius: "var(--radius-md, 8px)",
            border: "1px solid var(--border, #e2e8f0)",
            display: "flex",
            alignItems: "center",
            gap: 12
          }}
        >
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: "50%",
              background: "var(--blue-50, rgba(37,99,235,0.1))",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--blue-600, #2563eb)"
            }}
          >
            <Icon name="truck" size={18} />
          </div>
          <div>
            <div
              className="mono"
              style={{
                fontWeight: 700,
                fontSize: "14px",
                color: number.trim() ? "var(--text)" : "var(--text-subtle)",
              }}
            >
              {number.trim() || "e.g. MH 03 C 3843"}
            </div>
            <div className="text-muted text-small">
              {[vehicleType, capacityKg.trim() ? `${capacityKg.trim()} kg` : null].filter(Boolean).join(" • ")}
            </div>
          </div>
        </div>

        <Field
          label="Registration Number"
          required
          hint="Supports standard RTO (e.g. MH 03 C 3843) and Bharat Series (e.g. 22BH1234AB)."
          error={submitted ? numberError : undefined}
        >
          <Input
            value={number}
            onChange={(e) => handleNumberChange(e.target.value)}
            maxLength={30}
            autoFocus
            autoCapitalize="characters"
            style={{ textTransform: "uppercase" }}
            className="mono"
            placeholder="e.g. MH 03 C 3843 or 22BH1234AB"
          />
        </Field>

        <div className="grid-2" style={{ gap: 12 }}>
          <Field label="Vehicle Type">
            <Select
              value={vehicleType}
              onChange={(e) => setVehicleType(e.target.value)}
              options={VEHICLE_TYPES}
            />
          </Field>

          <Field label="Capacity (kg)" optional hint="Maximum cylinder load in kg.">
            <Input
              value={capacityKg}
              onChange={(e) => setCapacityKg(e.target.value.replace(/\D/g, ""))}
              inputMode="numeric"
              placeholder="e.g. 1500"
            />
          </Field>
        </div>

        <Field label="Notes" optional hint="Permit details, chassis notes, or driver comments.">
          <Textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            maxLength={255}
            placeholder="e.g. Permit valid till Dec; insurance due March"
          />
        </Field>

        {error ? (
          <Alert tone="error">
            {error.kind === "conflict" || /exist|duplicate|already/i.test(error.userMessage)
              ? `${normalised} is already on this merchant's fleet.`
              : (error.fieldErrors && Object.values(error.fieldErrors)[0]) || error.userMessage}
          </Alert>
        ) : null}
      </form>
    </Modal>
  );
}

export default AdminVehiclesPage;
