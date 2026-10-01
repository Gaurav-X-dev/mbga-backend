import { useEffect } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Icon, type IconName } from "../common/Icon";

export type Crumb = { label: string; to?: string };

type PageHeaderProps = {
  title: ReactNode;
  description?: ReactNode;
  /** Kept for callers; the trail itself is rendered once, in the top bar. */
  breadcrumbs?: Crumb[];
  actions?: ReactNode;
  meta?: ReactNode;
  /** Small label above the title, e.g. the module group. */
  eyebrow?: ReactNode;
  /** Plain-text title for the browser tab. */
  documentTitle?: string;
};

export function PageHeader({ title, description, actions, meta, eyebrow, documentTitle }: PageHeaderProps) {
  const tabTitle = documentTitle ?? (typeof title === "string" ? title : undefined);
  useEffect(() => {
    if (tabTitle) document.title = `${tabTitle} · MBGA`;
  }, [tabTitle]);
  return (
    <header className="page-header">
      <div className="page-header__text">
        {eyebrow ? <p className="page-header__eyebrow">{eyebrow}</p> : null}
        <span className="title-rule" aria-hidden="true" />
        <h1 className="page-title">{title}</h1>
        {description ? <p className="page-header__description">{description}</p> : null}
        {meta ? <div className="page-header__meta">{meta}</div> : null}
      </div>
      {actions ? <div className="page-header__actions">{actions}</div> : null}
    </header>
  );
}

/** Heading for a band of content inside a page ("Business health", "Analytics"). */
export function SectionHeader({
  title,
  description,
  actions,
  id
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  id?: string;
}) {
  return (
    <div className="section-header">
      <div>
        <h2 id={id} className="section-title">
          {title}
        </h2>
        {description ? <p className="section-header__description">{description}</p> : null}
      </div>
      {actions ? <div className="section-header__actions">{actions}</div> : null}
    </div>
  );
}

type CardProps = {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
  bodyless?: boolean;
  headingLevel?: 2 | 3;
};

export function Card({ title, subtitle, actions, children, footer, className, bodyless, headingLevel = 2 }: CardProps) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <section className={["card", className].filter(Boolean).join(" ")}>
      {title || actions ? (
        <div className="card__header">
          <div className="card__titles">
            {title ? <Heading className="card-title">{title}</Heading> : null}
            {subtitle ? <p className="card-subtitle">{subtitle}</p> : null}
          </div>
          {actions ? <div className="card__actions">{actions}</div> : null}
        </div>
      ) : null}
      {bodyless ? children : <div className="card__body">{children}</div>}
      {footer ? <div className="card__footer">{footer}</div> : null}
    </section>
  );
}

export type Tone = "blue" | "violet" | "orange" | "green" | "amber" | "red" | "slate";

/** "+8.4% this month" with a direction arrow. Direction is shown by icon and sign, not colour alone. */
export function MetricTrend({
  value,
  direction = "up",
  label,
  positive = direction === "up"
}: {
  value: string;
  direction?: "up" | "down" | "flat";
  label?: string;
  /** Whether this movement is good news (a drop in failures is positive). */
  positive?: boolean;
}) {
  const tone = direction === "flat" ? "flat" : positive ? "good" : "bad";
  return (
    <span className={`metric-trend metric-trend--${tone}`}>
      {direction !== "flat" ? <Icon name={direction === "up" ? "trendingUp" : "trendingDown"} size={14} /> : null}
      <strong>{value}</strong>
      {label ? <span>{label}</span> : null}
    </span>
  );
}

type StatCardProps = {
  label: string;
  value: ReactNode;
  icon: IconName;
  hint?: ReactNode;
  to?: string;
  linkLabel?: string;
  tone?: Tone;
  /** @deprecated use tone="orange" */
  accent?: boolean;
};

export function StatCard({ label, value, icon, hint, to, linkLabel, tone, accent }: StatCardProps) {
  const resolvedTone = tone ?? (accent ? "orange" : "blue");
  const content = (
    <>
      <div className="stat-card__top">
        <span className="stat-card__label">{label}</span>
        <span className={`stat-card__icon tone-${resolvedTone}`} aria-hidden="true">
          <Icon name={icon} size={18} />
        </span>
      </div>
      <span className="stat-card__value">{value}</span>
      {hint ? <span className="stat-card__hint">{hint}</span> : null}
      {to && linkLabel ? (
        <span className="stat-card__link">
          {linkLabel}
          <Icon name="arrowRight" size={14} />
        </span>
      ) : null}
    </>
  );
  if (to) {
    return (
      <Link to={to} className="stat-card stat-card--link">
        {content}
      </Link>
    );
  }
  return <div className="stat-card">{content}</div>;
}

/** Compact inline stat used in strips above tables. */
export function MiniStat({ label, value, icon, tone = "blue" }: { label: string; value: ReactNode; icon: IconName; tone?: Tone }) {
  return (
    <div className="mini-stat">
      <span className={`mini-stat__icon tone-${tone}`} aria-hidden="true">
        <Icon name={icon} size={16} />
      </span>
      <span className="mini-stat__text">
        <strong>{value}</strong>
        <span>{label}</span>
      </span>
    </div>
  );
}

/** Banner for screens that show preview data because the backend endpoint is not live yet. */
export function PreviewNotice({ children }: { children: ReactNode }) {
  return (
    <div className="preview-notice" role="note">
      <Icon name="info" size={16} />
      <p>
        <strong>Preview data.</strong> {children}
      </p>
    </div>
  );
}

export type DetailItem = { label: string; value: ReactNode; hidden?: boolean };

/** Read-only label/value list. Empty values show a dash rather than a blank. */
export function DetailsPanel({ items, columns = 2 }: { items: DetailItem[]; columns?: 1 | 2 }) {
  return (
    <dl className={`details${columns === 1 ? " details--single" : ""}`}>
      {items
        .filter((item) => !item.hidden)
        .map((item) => (
          <div key={item.label} className="details__item">
            <dt className="details__label">{item.label}</dt>
            <dd className="details__value">
              {item.value === null || item.value === undefined || item.value === "" ? (
                <span className="details__empty">Not provided</span>
              ) : (
                item.value
              )}
            </dd>
          </div>
        ))}
    </dl>
  );
}
