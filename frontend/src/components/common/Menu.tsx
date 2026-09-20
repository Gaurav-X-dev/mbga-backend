import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import { Icon, type IconName } from "./Icon";

export type MenuAction = {
  label: string;
  icon?: IconName;
  onSelect: () => void;
  danger?: boolean;
  disabled?: boolean;
  hidden?: boolean;
};

type MenuProps = {
  /** Accessible name for the trigger, e.g. "Actions for Sharma Gas Agency". */
  label: string;
  actions: MenuAction[];
  trigger?: (props: { open: boolean }) => ReactNode;
  triggerClassName?: string;
  header?: ReactNode;
};

/** Menu button pattern: Enter/Space/ArrowDown opens, arrows move, Escape closes and restores focus. */
export function Menu({ label, actions, trigger, triggerClassName = "icon-btn", header }: MenuProps) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const visible = actions.filter((action) => !action.hidden);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    const firstEnabled = itemRefs.current.find((item) => item && !item.disabled);
    firstEnabled?.focus();
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  if (visible.length === 0) return null;

  function close(restoreFocus = true) {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  }

  function onMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const items = itemRefs.current.filter((item): item is HTMLButtonElement => Boolean(item && !item.disabled));
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      items[(index + 1) % items.length]?.focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      items[(index - 1 + items.length) % items.length]?.focus();
    } else if (event.key === "Tab") {
      close(false);
    }
  }

  return (
    <div className="menu" ref={rootRef} onKeyDown={open ? onMenuKeyDown : undefined}>
      <button
        ref={triggerRef}
        type="button"
        className={triggerClassName}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={trigger ? undefined : label}
        title={trigger ? undefined : label}
        onClick={(event) => {
          event.stopPropagation();
          setOpen((value) => !value);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" && !open) {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        {trigger ? trigger({ open }) : <Icon name="more" />}
      </button>
      {open ? (
        <div className="menu__list" role="menu" id={menuId} aria-label={label}>
          {header ? <div className="menu__header">{header}</div> : null}
          {visible.map((action, index) => (
            <button
              key={action.label}
              ref={(element) => {
                itemRefs.current[index] = element;
              }}
              type="button"
              role="menuitem"
              className={`menu__item${action.danger ? " menu__item--danger" : ""}`}
              disabled={action.disabled}
              onClick={(event) => {
                event.stopPropagation();
                close(false);
                action.onSelect();
              }}
            >
              {action.icon ? <Icon name={action.icon} size={16} /> : null}
              {action.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
