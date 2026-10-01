import type { ReactNode } from "react";

import { Icon, type IconName } from "../common/Icon";

/** A titled group of fields laid out in a two-column grid (one column on phones). */
export function FormSection({
  title,
  description,
  icon,
  children,
  id
}: {
  title: string;
  description?: ReactNode;
  icon?: IconName;
  children: ReactNode;
  id?: string;
}) {
  const headingId = id ?? `section-${title.toLowerCase().replace(/\W+/g, "-")}`;
  return (
    <section className="form-section" aria-labelledby={headingId}>
      <div className="form-section__header">
        {icon ? (
          <span className="form-section__icon" aria-hidden="true">
            <Icon name={icon} size={18} />
          </span>
        ) : null}
        <div>
          <h2 id={headingId} className="card-title">
            {title}
          </h2>
          {description ? <p className="card-subtitle">{description}</p> : null}
        </div>
      </div>
      <div className="form-grid">{children}</div>
    </section>
  );
}

export type Step = { id: string; title: string; description: string; icon: IconName };

/**
 * Vertical step list for wizards. Completed steps can be revisited; later steps cannot be
 * skipped to, because their validation depends on the earlier ones.
 */
export function Stepper({
  steps,
  current,
  completed,
  onSelect
}: {
  steps: Step[];
  current: string;
  completed: ReadonlySet<string>;
  onSelect?: (id: string) => void;
}) {
  const currentIndex = steps.findIndex((step) => step.id === current);
  return (
    <nav className="stepper" aria-label="Form steps">
      <ol className="list-plain">
        {steps.map((step, index) => {
          const isCurrent = step.id === current;
          const isDone = completed.has(step.id) && !isCurrent;
          const reachable = index <= currentIndex || isDone;
          const state = isCurrent ? "current" : isDone ? "done" : "upcoming";
          const content = (
            <>
              <span className="stepper__marker" aria-hidden="true">
                {isDone ? <Icon name="check" size={16} /> : <Icon name={step.icon} size={16} />}
              </span>
              <span className="stepper__text">
                <span className="stepper__title">{step.title}</span>
                <span className="stepper__description">{step.description}</span>
              </span>
            </>
          );
          return (
            <li key={step.id} className={`stepper__item is-${state}`}>
              {onSelect && reachable && !isCurrent ? (
                <button type="button" className="stepper__button" onClick={() => onSelect(step.id)}>
                  {content}
                  <span className="sr-only">(completed, go back to this step)</span>
                </button>
              ) : (
                <div className="stepper__button" aria-current={isCurrent ? "step" : undefined}>
                  {content}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
