import { useEffect, useState } from "react";

/** Whole seconds remaining until `target` (epoch ms); 0 when reached or not set. */
export function useCountdown(target: number | null): number {
  const compute = () => (target ? Math.max(0, Math.ceil((target - Date.now()) / 1000)) : 0);
  const [remaining, setRemaining] = useState(compute);

  useEffect(() => {
    setRemaining(compute());
    if (!target) return;
    const timer = window.setInterval(() => {
      const next = compute();
      setRemaining(next);
      if (next === 0) window.clearInterval(timer);
    }, 1000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);

  return remaining;
}

export function formatCountdown(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}
