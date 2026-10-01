import { forwardRef } from "react";
import type { ButtonHTMLAttributes, MouseEvent, ReactNode } from "react";
import { Link, useNavigate, type LinkProps } from "react-router-dom";

import { Icon, type IconName } from "./Icon";

export type ButtonVariant = "primary" | "accent" | "secondary" | "ghost" | "danger" | "link";
export type ButtonSize = "sm" | "md" | "lg";

type CommonProps = {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: IconName;
  block?: boolean;
};

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  CommonProps & {
    loading?: boolean;
    /** Text announced while loading, e.g. "Saving…". */
    loadingText?: string;
  };

function classes({ variant = "primary", size = "md", block }: CommonProps, extra?: string) {
  return ["btn", `btn--${variant}`, size !== "md" && `btn--${size}`, block && "btn--block", extra]
    .filter(Boolean)
    .join(" ");
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant, size, icon, block, loading = false, loadingText, disabled, children, className, type = "button", ...rest },
  ref
) {
  return (
    <button
      ref={ref}
      type={type}
      className={classes({ variant, size, block }, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <span className="spinner" aria-hidden="true" /> : icon ? <Icon name={icon} size={16} /> : null}
      <span>{loading && loadingText ? loadingText : children}</span>
    </button>
  );
});

type ButtonLinkProps = LinkProps & CommonProps & { children: ReactNode };

function isModifiedEvent(event: MouseEvent<HTMLAnchorElement>) {
  return event.metaKey || event.altKey || event.ctrlKey || event.shiftKey;
}

export function ButtonLink({
  variant,
  size,
  icon,
  block,
  className,
  children,
  onClick,
  reloadDocument,
  replace,
  state,
  target,
  to,
  ...rest
}: ButtonLinkProps) {
  const navigate = useNavigate();

  return (
    <Link
      className={classes({ variant, size, block }, className)}
      onClick={(event) => {
        onClick?.(event);
        if (
          event.defaultPrevented ||
          reloadDocument ||
          target ||
          event.button !== 0 ||
          isModifiedEvent(event)
        ) {
          return;
        }
        event.preventDefault();
        navigate(to, { replace, state });
      }}
      reloadDocument={reloadDocument}
      replace={replace}
      state={state}
      target={target}
      to={to}
      {...rest}
    >
      {icon ? <Icon name={icon} size={16} /> : null}
      <span>{children}</span>
    </Link>
  );
}

type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  icon: IconName;
  /** Required accessible name. */
  label: string;
};

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon, label, className, type = "button", ...rest },
  ref
) {
  return (
    <button
      ref={ref}
      type={type}
      className={["icon-btn", className].filter(Boolean).join(" ")}
      aria-label={label}
      title={label}
      {...rest}
    >
      <Icon name={icon} />
    </button>
  );
});
