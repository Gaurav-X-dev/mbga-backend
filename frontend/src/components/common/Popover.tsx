import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";

type PopoverProps = {
  /** Accessible name for the trigger button. */
  label: string;
  trigger: ReactNode;
  triggerClassName?: string;
  /** Content receives a close callback so links inside can dismiss the panel. */
  children: (close: () => void) => ReactNode;
  align?: "start" | "end";
  panelClassName?: string;
};

/** Disclosure-style popover: click to open, Escape or outside click to close, focus returns. */
export function Popover({ label, trigger, triggerClassName = "icon-btn", children, align = "end", panelClassName }: PopoverProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const close = () => setOpen(false);

  return (
    <div className="popover" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className={triggerClassName}
        aria-label={label}
        title={label}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        {trigger}
      </button>
      {open ? (
        <div id={panelId} className={["popover__panel", `popover__panel--${align}`, panelClassName].filter(Boolean).join(" ")}>
          {children(close)}
        </div>
      ) : null}
    </div>
  );
}
