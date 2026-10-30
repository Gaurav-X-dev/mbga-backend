import { IconButton } from "../../components/common/Button";

/**
 * A KYC document number, hidden until asked for.
 *
 * Callers supply a masked value or an explicitly authorized, on-demand full value.
 * Hiding the supplied number by default keeps
 * it off a screen that is being shared or looked over.
 */
export function DocumentNumber({ value, shown, onToggle, wrap = false, disabled = false }: { disabled?: boolean; wrap?: boolean; value: string | null | undefined; shown: boolean; onToggle: () => void }) {
  if (!value) return <span className="text-muted">No number given</span>;
  return (
    <span className="row" style={{ gap: 4, flexWrap: wrap ? "wrap" : "nowrap", alignItems: "center" }}>
      <span className="text-muted text-small">No.</span>
      <span className="mono" aria-live="polite" style={{ letterSpacing: shown ? undefined : "0.15em", overflowWrap: wrap ? "anywhere" : undefined, minWidth: wrap ? 0 : undefined }}>
        {shown ? value : "•".repeat(Math.min(Math.max(value.replace(/\s/g, "").length, 8), 14))}
      </span>
      <IconButton icon={shown ? "lock" : "eye"} label={shown ? "Hide number" : "Show number"} onClick={onToggle} disabled={disabled} />
    </span>
  );
}
