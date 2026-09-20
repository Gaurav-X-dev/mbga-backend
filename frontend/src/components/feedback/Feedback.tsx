import type { CSSProperties, ReactNode } from "react";

import { normalizeError } from "../../api/errors";
import { Button } from "../common/Button";
import { Icon, type IconName } from "../common/Icon";

type AlertTone = "error" | "success" | "warning" | "info";

const ALERT_ICONS: Record<AlertTone, IconName> = {
  error: "alert",
  success: "checkCircle",
  warning: "warning",
  info: "info"
};

type AlertProps = {
  tone: AlertTone;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
};

/** Errors are announced assertively, other messages politely. */
export function Alert({ tone, title, children, action, className }: AlertProps) {
  return (
    <div
      className={["alert", `alert--${tone}`, className].filter(Boolean).join(" ")}
      role={tone === "error" ? "alert" : "status"}
    >
      <Icon name={ALERT_ICONS[tone]} />
      <div className="alert__body">
        {title ? <p className="alert__title">{title}</p> : null}
        {children ? <div>{children}</div> : null}
      </div>
      {action}
    </div>
  );
}

/** Shows the safe message for any thrown value. */
export function InlineError({ error, title, onRetry }: { error: unknown; title?: string; onRetry?: () => void }) {
  if (!error) return null;
  const appError = normalizeError(error);
  return (
    <Alert
      tone="error"
      title={title}
      action={
        onRetry ? (
          <Button variant="secondary" size="sm" onClick={onRetry}>
            Try again
          </Button>
        ) : undefined
      }
    >
      {appError.userMessage}
    </Alert>
  );
}

export function SuccessMessage({ title, children }: { title?: ReactNode; children?: ReactNode }) {
  return (
    <Alert tone="success" title={title}>
      {children}
    </Alert>
  );
}

type StateProps = {
  icon?: IconName;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  tone?: "default" | "error" | "warning";
};

export function EmptyState({ icon = "box", title, description, action, tone = "default" }: StateProps) {
  return (
    <div className="state">
      <span className={`state__icon${tone !== "default" ? ` state__icon--${tone}` : ""}`} aria-hidden="true">
        <Icon name={icon} size={26} />
      </span>
      <h2 className="state__title">{title}</h2>
      {description ? <p className="state__description">{description}</p> : null}
      {action ? <div className="row">{action}</div> : null}
    </div>
  );
}

/** Full error state for a failed page or section, with a retry action where safe. */
export function ErrorState({ error, onRetry, title }: { error: unknown; onRetry?: () => void; title?: string }) {
  const appError = normalizeError(error);
  const isPermission = appError.kind === "forbidden";
  const isMissing = appError.kind === "not_found";
  const isOffline = appError.kind === "network" || appError.kind === "timeout";
  const heading =
    title ??
    (isPermission
      ? "You don’t have access to this"
      : isMissing
        ? "We couldn’t find this record"
        : isOffline
          ? "Can’t reach the server"
          : "Something went wrong");
  const canRetry = onRetry && !isPermission && !isMissing && appError.kind !== "validation";
  return (
    <div role="alert">
      <EmptyState
        icon={isPermission ? "lock" : isOffline ? "refresh" : "alert"}
        tone={isPermission ? "warning" : "error"}
        title={heading}
        description={appError.userMessage}
        action={
          canRetry ? (
            <Button variant="secondary" icon="refresh" onClick={onRetry}>
              Try again
            </Button>
          ) : undefined
        }
      />
    </div>
  );
}

export function Skeleton({ width = "100%", height = 14, style }: { width?: CSSProperties["width"]; height?: number; style?: CSSProperties }) {
  return <span className="skeleton" style={{ width, height, ...style }} />;
}

/** Placeholder that keeps layout stable while data loads. */
export function LoadingSkeleton({ rows = 5, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-live="polite" className="stack" style={{ padding: "var(--space-5)" }}>
      <span className="sr-only">{label}…</span>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="row" aria-hidden="true" style={{ flexWrap: "nowrap" }}>
          <Skeleton width={36} height={36} style={{ borderRadius: "50%", flexShrink: 0 }} />
          <div className="stack" style={{ gap: 6, flex: 1 }}>
            <Skeleton width={`${45 + ((index * 13) % 30)}%`} />
            <Skeleton width={`${25 + ((index * 7) % 20)}%`} height={10} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function RefreshIndicator({ active }: { active: boolean }) {
  if (!active) return null;
  return (
    <span className="refresh-indicator" role="status">
      <span className="spinner" aria-hidden="true" />
      Updating…
    </span>
  );
}

export function FullPageLoader({ label = "Loading your workspace" }: { label?: string }) {
  return (
    <div className="full-page-state" role="status" aria-live="polite">
      <div className="stack" style={{ alignItems: "center" }}>
        <span className="spinner" style={{ width: 32, height: 32, color: "var(--navy-700)" }} aria-hidden="true" />
        <p className="text-muted">{label}…</p>
      </div>
    </div>
  );
}
