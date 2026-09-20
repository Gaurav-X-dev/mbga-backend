import type { ReactNode } from "react";

import { initials } from "../../utils/format";
import { statusMeta, type Tone } from "../../utils/labels";

/** Status is always shown as text as well as colour. */
export function StatusBadge({ status }: { status: string | null | undefined }) {
  const meta = statusMeta(status);
  return <span className={`badge badge--${meta.tone}`}>{meta.label}</span>;
}

export function Badge({ tone = "neutral", plain = true, children }: { tone?: Tone; plain?: boolean; children: ReactNode }) {
  return <span className={`badge badge--${tone}${plain ? " badge--plain" : ""}`}>{children}</span>;
}

export function UserAvatar({ name, size = "md" }: { name: string | null | undefined; size?: "md" | "lg" }) {
  return (
    <span className={`avatar${size === "lg" ? " avatar--lg" : ""}`} aria-hidden="true">
      {initials(name)}
    </span>
  );
}

export function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      MBGA
    </span>
  );
}
