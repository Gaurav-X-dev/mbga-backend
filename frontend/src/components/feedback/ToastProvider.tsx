import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PropsWithChildren } from "react";

import { IconButton } from "../common/Button";
import { Icon } from "../common/Icon";
import { ToastContext, type ToastApi, type ToastTone } from "./toast-context";

type ToastItem = { id: number; message: string; tone: ToastTone };

const DURATION_MS = 5000;

export function ToastProvider({ children }: PropsWithChildren) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, number>());

  const dismiss = useCallback((id: number) => {
    setToasts((items) => items.filter((item) => item.id !== id));
    const timer = timers.current.get(id);
    if (timer) window.clearTimeout(timer);
    timers.current.delete(id);
  }, []);

  const show = useCallback(
    (message: string, tone: ToastTone = "info") => {
      const id = nextId.current++;
      setToasts((items) => [...items.slice(-3), { id, message, tone }]);
      timers.current.set(
        id,
        window.setTimeout(() => dismiss(id), tone === "error" ? DURATION_MS * 2 : DURATION_MS)
      );
    },
    [dismiss]
  );

  useEffect(() => {
    const map = timers.current;
    return () => map.forEach((timer) => window.clearTimeout(timer));
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      show,
      success: (message) => show(message, "success"),
      error: (message) => show(message, "error")
    }),
    [show]
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toast-region" aria-live="polite" aria-relevant="additions">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast toast--${toast.tone}`} role={toast.tone === "error" ? "alert" : "status"}>
            <Icon name={toast.tone === "success" ? "checkCircle" : toast.tone === "error" ? "alert" : "info"} />
            <p className="toast__message">{toast.message}</p>
            <IconButton icon="x" label="Dismiss notification" onClick={() => dismiss(toast.id)} />
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
