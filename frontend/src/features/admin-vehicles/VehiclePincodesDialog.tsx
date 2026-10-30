import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { normalizeError } from "../../api/errors";
import { queryKeys } from "../../api/query-keys";
import { getVehiclePincodes, setVehiclePincodes, type Vehicle } from "../../api/vehicles.api";
import { Button, IconButton } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { Badge } from "../../components/common/StatusBadge";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert, InlineError, LoadingSkeleton } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Input } from "../../components/forms/Field";

/** Every 6-digit run in what was typed or pasted. */
const parsePincodes = (text: string) => text.match(/\b\d{6}\b/g) ?? [];

export function VehiclePincodesDialog({
  merchantId,
  vehicle,
  onClose
}: {
  merchantId: string;
  vehicle: Vehicle | null;
  onClose: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [list, setList] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [pinError, setPinError] = useState("");
  const [filterQuery, setFilterQuery] = useState("");

  const query = useQuery({
    queryKey: queryKeys.vehicles.pincodes(merchantId, vehicle?.id ?? ""),
    queryFn: ({ signal }) => getVehiclePincodes(merchantId, vehicle!.id, signal),
    enabled: Boolean(vehicle)
  });

  useEffect(() => {
    if (query.data) setList([...query.data.pincodes].sort());
  }, [query.data]);

  useEffect(() => {
    if (vehicle) {
      setDraft("");
      setPinError("");
      setFilterQuery("");
    }
  }, [vehicle]);

  const saved = [...(query.data?.pincodes ?? [])].sort().join(",");
  const changed = list.join(",") !== saved;

  const mutation = useMutation({
    mutationFn: () => setVehiclePincodes(merchantId, vehicle!.id, list),
    onSuccess: (result) => {
      queryClient.setQueryData(queryKeys.vehicles.pincodes(merchantId, vehicle!.id), result);
      void queryClient.invalidateQueries({ queryKey: queryKeys.vehicles.all });
      toast.success(`Mapped ${result.pincodes.length} pincodes to ${vehicle!.number}.`);
      onClose();
    }
  });

  function handleAdd() {
    const raw = draft.trim();
    if (!raw) {
      setPinError("Enter a 6-digit pincode");
      return;
    }

    // Check if multiple pincodes are pasted or separated
    const parsed = parsePincodes(raw);
    if (parsed.length > 1) {
      const validNewPins = parsed.filter((p) => !p.startsWith("0") && !list.includes(p));
      if (validNewPins.length === 0) {
        setPinError("All entered pincodes are already added or start with 0");
        return;
      }
      setList((prev) => [...new Set([...prev, ...validNewPins])].sort());
      setDraft("");
      setPinError("");
      return;
    }

    // Single pincode validation matching merchant app
    const clean = raw.replace(/\D/g, "");
    if (clean.length !== 6) {
      setPinError("Pincode must be exactly 6 digits");
      return;
    }
    if (clean.startsWith("0")) {
      setPinError("Pincode cannot start with 0");
      return;
    }
    if (list.includes(clean)) {
      setPinError("Pincode already added");
      return;
    }

    setList((prev) => [...prev, clean].sort());
    setDraft("");
    setPinError("");
  }

  function handleRemove(pinToRemove: string) {
    setList((prev) => prev.filter((p) => p !== pinToRemove));
  }

  function handleClearAll() {
    setList([]);
    setDraft("");
    setPinError("");
  }

  const displayedList = filterQuery.trim()
    ? list.filter((p) => p.includes(filterQuery.trim()))
    : list;

  const error = mutation.error ? normalizeError(mutation.error) : null;

  return (
    <Modal
      open={vehicle !== null}
      title={vehicle ? `Manage Vehicle Pincodes` : "Pincodes"}
      description={vehicle ? `${vehicle.number} · ${vehicle.label || "Fleet Vehicle"}` : undefined}
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
          <Button
            icon="check"
            onClick={() => mutation.mutate()}
            disabled={!changed || query.isLoading}
            loading={mutation.isPending}
            loadingText="Saving…"
          >
            {changed ? `Save pincodes (${list.length})` : "Save pincodes"}
          </Button>
        </>
      }
    >
      {query.isLoading ? (
        <LoadingSkeleton rows={3} label="Loading mapped pincodes" />
      ) : query.error ? (
        <InlineError error={query.error} title="Pincodes could not be loaded" onRetry={() => void query.refetch()} />
      ) : (
        <div className="stack" style={{ gap: 14 }}>
          {/* Vehicle summary header */}
          {vehicle ? (
            <div
              className="row-between"
              style={{
                alignItems: "center",
                padding: "10px 14px",
                background: "var(--surface-muted, #f8fafc)",
                borderRadius: "var(--radius-md, 8px)",
                border: "1px solid var(--border, #e2e8f0)"
              }}
            >
              <div className="row" style={{ gap: 10, alignItems: "center" }}>
                <div
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: "50%",
                    background: "var(--blue-50, rgba(37,99,235,0.1))",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "var(--blue-600, #2563eb)"
                  }}
                >
                  <Icon name="truck" size={16} />
                </div>
                <div>
                  <strong className="mono" style={{ fontSize: "14px", color: "var(--text)" }}>
                    {vehicle.number}
                  </strong>
                  {vehicle.label ? (
                    <div className="text-muted text-small">{vehicle.label}</div>
                  ) : null}
                </div>
              </div>
              <Badge tone={vehicle.isActive ? "success" : "neutral"}>
                {vehicle.isActive ? "In service" : "Retired"}
              </Badge>
            </div>
          ) : null}

          {/* Exact banner matching merchant app */}
          <Alert tone="info">
            <strong>Important:</strong> Saving replaces previous mapping. Complete latest pincode list is sent. Merchant's first vehicle mapping activates pincode enforcement.
          </Alert>

          {/* Add Pincode Form */}
          <form
            className="row"
            style={{ gap: 8, alignItems: "flex-end" }}
            onSubmit={(event) => {
              event.preventDefault();
              handleAdd();
            }}
          >
            <Field
              label="Add Pincode"
              hint="Type 6 digits (e.g. 122018) or paste comma/space separated pincodes."
              error={pinError || undefined}
              className="grow"
            >
              <Input
                value={draft}
                onChange={(e) => {
                  const val = e.target.value;
                  setDraft(val);
                  if (pinError) setPinError("");
                }}
                inputMode="numeric"
                maxLength={40}
                placeholder="6-digit pincode (e.g. 122018)"
                autoFocus
              />
            </Field>
            <Button
              type="submit"
              variant="secondary"
              icon="plus"
              disabled={!draft.trim()}
            >
              Add
            </Button>
          </form>

          {/* Section: Mapped Pincodes */}
          <div className="stack" style={{ gap: 8 }}>
            <div className="row-between" style={{ alignItems: "center" }}>
              <div className="row" style={{ gap: 8, alignItems: "center" }}>
                <span style={{ fontWeight: 600, fontSize: "13px" }}>
                  Mapped Pincodes ({list.length})
                </span>
                {list.length > 0 ? (
                  <span
                    style={{
                      background: "var(--color-brand-subtle, rgba(37,99,235,0.1))",
                      color: "var(--color-brand, #2563eb)",
                      padding: "1px 6px",
                      borderRadius: 999,
                      fontSize: "11px",
                      fontWeight: 600
                    }}
                  >
                    {list.length}
                  </span>
                ) : null}
              </div>

              {list.length > 0 ? (
                <button
                  type="button"
                  className="btn--link text-small"
                  onClick={handleClearAll}
                  style={{ color: "var(--color-danger, #ef4444)" }}
                >
                  Clear all
                </button>
              ) : null}
            </div>

            {list.length > 10 ? (
              <Input
                value={filterQuery}
                onChange={(e) => setFilterQuery(e.target.value)}
                placeholder="Filter mapped pincodes…"
                style={{ height: 32, fontSize: "12px" }}
              />
            ) : null}

            {displayedList.length > 0 ? (
              <ul
                className="list-plain row"
                style={{
                  gap: 6,
                  flexWrap: "wrap",
                  maxHeight: 180,
                  overflowY: "auto",
                  padding: "8px",
                  background: "var(--surface-1, #fff)",
                  border: "1px solid var(--border, #e2e8f0)",
                  borderRadius: "var(--radius-md, 8px)"
                }}
                aria-label="Mapped pincodes"
              >
                {displayedList.map((pin) => (
                  <li
                    key={pin}
                    className="vehicle-pincode-chip"
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                      padding: "2px 6px 2px 10px"
                    }}
                  >
                    <Icon name="mapPin" size={11} />
                    <span>{pin}</span>
                    <IconButton
                      icon="x"
                      label={`Remove ${pin}`}
                      onClick={() => handleRemove(pin)}
                      style={{ padding: 2, marginLeft: 2 }}
                    />
                  </li>
                ))}
              </ul>
            ) : list.length > 0 ? (
              <p className="text-muted text-small" style={{ margin: 0 }}>
                No pincodes match “{filterQuery}”.
              </p>
            ) : (
              <div
                style={{
                  padding: "16px",
                  textAlign: "center",
                  background: "var(--surface-muted, #f8fafc)",
                  borderRadius: "var(--radius-md, 8px)",
                  border: "1px dashed var(--border, #cbd5e1)"
                }}
              >
                <p className="text-muted text-small" style={{ margin: 0 }}>
                  No pincodes mapped yet. When no pincodes are mapped, the vehicle is offered for all deliveries without pincode-based prioritization.
                </p>
              </div>
            )}
          </div>

          {error ? (
            <Alert tone="error">
              {(error.fieldErrors && Object.values(error.fieldErrors)[0]) || error.userMessage}
            </Alert>
          ) : null}
        </div>
      )}
    </Modal>
  );
}

export default VehiclePincodesDialog;
