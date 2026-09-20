import { cloneElement, forwardRef, isValidElement, useId } from "react";
import type {
  InputHTMLAttributes,
  ReactElement,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes
} from "react";

import { Icon } from "../common/Icon";

type FieldProps = {
  label: ReactNode;
  hint?: ReactNode;
  error?: string;
  required?: boolean;
  optional?: boolean;
  className?: string;
  /** The control; receives id, aria-describedby, aria-invalid and aria-required. */
  children: ReactElement;
  /** Visually hide the label (it is still announced). */
  hideLabel?: boolean;
};

/** Wraps a single control with a real <label>, helper text and an announced error. */
export function Field({ label, hint, error, required, optional, className, children, hideLabel }: FieldProps) {
  const generatedId = useId();
  const childProps = (isValidElement(children) ? children.props : {}) as { id?: string };
  const id = childProps.id ?? generatedId;
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <div className={["field", className].filter(Boolean).join(" ")}>
      <label htmlFor={id} className={hideLabel ? "sr-only" : "field__label"}>
        {label}
        {required ? (
          <span className="field__required" aria-hidden="true">
            *
          </span>
        ) : null}
        {optional ? <span className="field__optional">(optional)</span> : null}
      </label>
      {cloneElement(children as ReactElement<Record<string, unknown>>, {
        id,
        "aria-describedby": describedBy,
        "aria-invalid": error ? true : undefined,
        "aria-required": required || undefined
      })}
      {hint ? (
        <p id={hintId} className="field__hint">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="field__error">
          <Icon name="alert" size={16} />
          <span>{error}</span>
        </p>
      ) : null}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...rest },
  ref
) {
  return <input ref={ref} className={["input", className].filter(Boolean).join(" ")} {...rest} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...rest }, ref) {
    return <textarea ref={ref} className={["textarea", className].filter(Boolean).join(" ")} {...rest} />;
  }
);

export type SelectOption = { value: string; label: string; disabled?: boolean };

type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & {
  options: SelectOption[];
  placeholder?: string;
};

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { className, options, placeholder, ...rest },
  ref
) {
  return (
    <select ref={ref} className={["select", className].filter(Boolean).join(" ")} {...rest}>
      {placeholder !== undefined ? <option value="">{placeholder}</option> : null}
      {options.map((option) => (
        <option key={option.value} value={option.value} disabled={option.disabled}>
          {option.label}
        </option>
      ))}
    </select>
  );
});

/**
 * Indian mobile number with a fixed +91 prefix. The user types 10 digits;
 * callers normalise with `normalizeMobileNumber` before sending.
 */
export const PhoneInput = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function PhoneInput(
  { className, ...rest },
  ref
) {
  return (
    <div className="input-group">
      <span className="input-group__addon" aria-hidden="true">
        +91
      </span>
      <input
        ref={ref}
        type="tel"
        inputMode="tel"
        autoComplete="tel-national"
        placeholder="98765 43210"
        maxLength={16}
        className={["input", className].filter(Boolean).join(" ")}
        {...rest}
      />
    </div>
  );
});

type SearchInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { label: string };

export function SearchInput({ label, className, ...rest }: SearchInputProps) {
  return (
    <div className={["search-input", className].filter(Boolean).join(" ")}>
      <Icon name="search" size={16} />
      <input type="search" className="input" aria-label={label} {...rest} />
    </div>
  );
}

type CheckboxProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & {
  label: ReactNode;
  description?: ReactNode;
};

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  { label, description, className, ...rest },
  ref
) {
  return (
    <label className={["checkbox", className].filter(Boolean).join(" ")}>
      <input ref={ref} type="checkbox" {...rest} />
      <span className="checkbox__text">
        <span>{label}</span>
        {description ? <span className="checkbox__description">{description}</span> : null}
      </span>
    </label>
  );
});

export type RadioOption = { value: string; label: string; description?: string };

type RadioGroupProps = {
  legend: string;
  name: string;
  value: string;
  options: RadioOption[];
  onChange: (value: string) => void;
  error?: string;
  required?: boolean;
  disabled?: boolean;
};

/** Card-style radio group rendered as a real fieldset/legend. */
export function RadioGroup({ legend, name, value, options, onChange, error, required, disabled }: RadioGroupProps) {
  const errorId = useId();
  return (
    <fieldset className="field" style={{ border: 0, margin: 0, padding: 0 }} aria-describedby={error ? errorId : undefined}>
      <legend className="field__label" style={{ marginBottom: "var(--space-2)" }}>
        {legend}
        {required ? (
          <span className="field__required" aria-hidden="true">
            *
          </span>
        ) : null}
      </legend>
      <div className="radio-cards">
        {options.map((option) => (
          <label key={option.value} className="radio-card">
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              disabled={disabled}
              onChange={() => onChange(option.value)}
            />
            <span>
              <span className="radio-card__title">{option.label}</span>
              {option.description ? <span className="radio-card__description">{option.description}</span> : null}
            </span>
          </label>
        ))}
      </div>
      {error ? (
        <p id={errorId} className="field__error">
          <Icon name="alert" size={16} />
          <span>{error}</span>
        </p>
      ) : null}
    </fieldset>
  );
}
