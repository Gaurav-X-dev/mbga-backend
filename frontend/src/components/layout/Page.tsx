import { useEffect } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Icon, type IconName } from "../common/Icon";

export type Crumb = { label: string; to?: string };

export function Breadcrumbs({ items }: { items: Crumb[] }) {
  if (items.length === 0) return null;
  return (
    <nav aria-label="Breadcrumb" className="breadcrumbs">
      <ol>
        {items.map((item, index) => {
          const last = index === items.length - 1;
          return (
            <li key={`${item.label}-${index}`}>
              {item.to && !last ? <Link to={item.to}>{item.label}</Link> : <span aria-current={last ? "page" : undefined}>{item.label}</span>}
              {!last ? <Icon name="chevronRight" size={14} /> : null}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

type PageHeaderProps = {
  title: ReactNode;
  description?: ReactNode;
  breadcrumbs?: Crumb[];
  actions?: ReactNode;
  meta?: ReactNode;
  /** Plain-text title for the browser tab. */
  documentTitle?: string;
};

export function PageHeader({ title, description, breadcrumbs, actions, meta, documentTitle }: PageHeaderProps) {
  const tabTitle = documentTitle ?? (typeof title === "string" ? title : undefined);
  useEffect(() => {
    if (tabTitle) document.title = `${tabTitle} · MBGA`;
  }, [tabTitle]);
  return (
    <header className="page-header">
      <div className="page-header__text">
        {breadcrumbs ? <Breadcrumbs items={breadcrumbs} /> : null}
        <h1 className="page-title">{title}</h1>
        {description ? <p className="text-muted">{description}</p> : null}
        {meta ? <div className="row">{meta}</div> : null}
      </div>
      {actions ? <div className="page-header__actions">{actions}</div> : null}
    </header>
  );
}

type CardProps = {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
  bodyless?: boolean;
  headingLevel?: 2 | 3;
};

export function Card({ title, actions, children, footer, className, bodyless, headingLevel = 2 }: CardProps) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <section className={["card", className].filter(Boolean).join(" ")}>
      {title || actions ? (
        <div className="card__header">
          {title ? <Heading className="section-title">{title}</Heading> : <span />}
          {actions ? <div className="row">{actions}</div> : null}
        </div>
      ) : null}
      {bodyless ? children : <div className="card__body">{children}</div>}
      {footer ? <div className="card__footer">{footer}</div> : null}
    </section>
  );
}

type StatCardProps = {
  label: string;
  value: ReactNode;
  icon: IconName;
  hint?: ReactNode;
  to?: string;
  linkLabel?: string;
  accent?: boolean;
};

export function StatCard({ label, value, icon, hint, to, linkLabel, accent }: StatCardProps) {
  const content = (
    <>
      <span className="stat-card__label">
        <span className={`stat-card__icon${accent ? " stat-card__icon--accent" : ""}`} aria-hidden="true">
          <Icon name={icon} size={16} />
        </span>
        {label}
      </span>
      <span className="stat-card__value">{value}</span>
      {hint ? <span className="stat-card__hint">{hint}</span> : null}
      {to && linkLabel ? (
        <span className="stat-card__link">
          {linkLabel} <span aria-hidden="true">→</span>
        </span>
      ) : null}
    </>
  );
  if (to) {
    return (
      <Link to={to} className="stat-card">
        {content}
      </Link>
    );
  }
  return <div className="stat-card">{content}</div>;
}

export type DetailItem = { label: string; value: ReactNode; hidden?: boolean };

/** Read-only label/value list. Empty values show a dash rather than a blank. */
export function DetailsPanel({ items }: { items: DetailItem[] }) {
  return (
    <dl className="details">
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
