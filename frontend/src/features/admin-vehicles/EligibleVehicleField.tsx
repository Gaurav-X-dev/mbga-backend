import { useEffect, useState } from "react";

import type { EligibleVehicle } from "../../api/vehicles.api";
import { Field, Input, Select } from "../../components/forms/Field";

const OTHER = "__other__";

/** Matching vans first (by the backend's priority), then by number. */
function sortEligible(vehicles: EligibleVehicle[]) {
  return [...vehicles].sort(
    (a, b) =>
      Number(Boolean(b.matchedPincode)) - Number(Boolean(a.matchedPincode)) ||
      (a.priority ?? Number.MAX_SAFE_INTEGER) - (b.priority ?? Number.MAX_SAFE_INTEGER) ||
      a.number.localeCompare(b.number)
  );
}

/**
 * Whether taking this van would clash.
 *
 * The rule is one van, one driver, one day - so a van already out is only a clash for a
 * *different* driver. The same driver filling a round through the morning is the ordinary
 * case, which is why a busy van stays on the list rather than being hidden: dropping it would
 * block the assignment that is actually correct.
 *
 * With no driver chosen yet there is nothing to compare against, so nothing is flagged.
 */
function clashesWith(vehicle: EligibleVehicle | undefined, driverUserId: string | null | undefined) {
  if (!vehicle?.busyWithDriverUserId || !driverUserId) return false;
  return vehicle.busyWithDriverUserId !== driverUserId;
}

/**
 * Vehicle choice for an assignment, from the backend's eligible list (vans serving the
 * delivery pincode come first). "Other" keeps a typed number possible when the list is empty
 * or could not load, so an assignment is never blocked by the lookup.
 *
 * A van already out that day says so on its own row. That sentence used to arrive only after
 * Confirm, as a 422 from the assignment - the operator had filled the whole form before
 * finding out the van was taken.
 */
export function EligibleVehicleField({
  vehicles,
  loading,
  failed,
  value,
  onChange,
  error,
  autoFocus,
  selectedDriverUserId
}: {
  vehicles: EligibleVehicle[] | undefined;
  loading: boolean;
  failed: boolean;
  value: string;
  onChange: (vehicleNumber: string) => void;
  error?: string;
  autoFocus?: boolean;
  /** The driver chosen alongside this van, so the clash can be judged before Confirm. */
  selectedDriverUserId?: string | null;
}) {
  const list = sortEligible(vehicles ?? []);
  const known = list.some((v) => v.number === value);
  const [typing, setTyping] = useState(false);

  // No list to choose from: fall back to typing.
  useEffect(() => {
    if (!loading && (failed || list.length === 0)) setTyping(true);
  }, [loading, failed, list.length]);
  // A value that is not on the list (e.g. the slip's current van) is shown as typed.
  useEffect(() => {
    if (value && list.length && !known) setTyping(true);
  }, [value, known, list.length]);

  const chosen = list.find((v) => v.number === value);
  const clash = clashesWith(chosen, selectedDriverUserId);

  const hint = loading
    ? "Loading eligible vans…"
    : failed
      ? "Eligible vans could not be loaded; type the number."
      : list.length === 0
        ? "No eligible vans for this pincode; type the number."
        : `${list.filter((v) => v.matchedPincode).length} of ${list.length} serve this pincode.`;

  return (
    <Field label="Vehicle" required error={error} hint={hint}>
      {typing && (failed || list.length === 0) ? (
        <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder="e.g. GJ01AB1234" maxLength={20} autoFocus={autoFocus} />
      ) : (
        <div className="stack" style={{ gap: 6 }}>
          <Select
            value={typing ? OTHER : value}
            disabled={loading}
            onChange={(e) => {
              if (e.target.value === OTHER) {
                setTyping(true);
                onChange("");
              } else {
                setTyping(false);
                onChange(e.target.value);
              }
            }}
            placeholder={loading ? "Loading…" : "Choose a van"}
            autoFocus={autoFocus}
            options={[
              ...list.map((v) => ({
                value: v.number,
                label: `${v.number}${v.label ? ` · ${v.label}` : ""}${v.matchedPincode ? ` · serves ${v.matchedPincode}` : ""}${
                  v.busyWithDriverName ? ` · out with ${v.busyWithDriverName}` : ""
                }`
              })),
              { value: OTHER, label: "Other — type a number" }
            ]}
          />
          {typing ? <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder="Vehicle number" maxLength={20} aria-label="Vehicle number" /> : null}
          {clash ? (
            <p role="alert" style={{ margin: 0, color: "var(--color-danger, #c0392b)", fontSize: "0.85em" }}>
              {chosen?.number} is already out with {chosen?.busyWithDriverName} today. Pick another
              van, or assign {chosen?.busyWithDriverName} to this round as well.
            </p>
          ) : null}
        </div>
      )}
    </Field>
  );
}
