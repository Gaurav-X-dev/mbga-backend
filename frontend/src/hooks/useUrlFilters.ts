import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useDebouncedValue } from "./useDebouncedValue";

const MERCHANT_KEY = "mbga.web.selected-merchant";

function readRememberedMerchant(): string {
  try {
    return window.localStorage.getItem(MERCHANT_KEY) ?? "";
  } catch {
    return "";
  }
}

function rememberMerchant(value: string): void {
  try {
    if (value) window.localStorage.setItem(MERCHANT_KEY, value);
    else window.localStorage.removeItem(MERCHANT_KEY);
  } catch {
    // Storing is a convenience; the page works without it.
  }
}

/**
 * List filters and page number kept in the address bar, so filtered views can be
 * bookmarked, shared and restored with the back button.
 */
export function useUrlFilters<K extends string>(keys: readonly K[]) {
  const [params, setParams] = useSearchParams();

  const values = useMemo(() => {
    const result = {} as Record<K, string>;
    keys.forEach((key) => {
      result[key] = params.get(key) ?? "";
    });
    // Hand back the remembered agency on the very first render, not after an effect.
    //
    // Each page also defaults to the first agency in the list, and both run in the same
    // commit: setting the address bar from an effect does not update `params` in time, so
    // that default still saw an empty merchant and wrote over the remembered one. Filling
    // it here means the page sees a merchant already chosen and leaves it alone.
    if (!result["merchant" as K] && (keys as readonly string[]).includes("merchant")) {
      result["merchant" as K] = readRememberedMerchant();
    }
    return result;
    // keys is a static list per page
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);

  const setFilter = useCallback(
    (key: K, value: string) => {
      if (key === "merchant") rememberMerchant(value);
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          if (value) next.set(key, value);
          else next.delete(key);
          next.delete("page");
          return next;
        },
        { replace: true }
      );
    },
    [setParams]
  );

  const tracksMerchant = (keys as readonly string[]).includes("merchant");
  useEffect(() => {
    if (!tracksMerchant || params.get("merchant")) return;
    const remembered = readRememberedMerchant();
    if (remembered) setFilter("merchant" as K, remembered);
  }, [tracksMerchant, params, setFilter]);

  const setPage = useCallback(
    (nextPage: number) => {
      setParams((previous) => {
        const next = new URLSearchParams(previous);
        if (nextPage <= 1) next.delete("page");
        else next.set("page", String(nextPage));
        return next;
      });
    },
    [setParams]
  );

  const reset = useCallback(() => setParams(new URLSearchParams(), { replace: true }), [setParams]);

  /** Clears several filters in one navigation; back-to-back setFilter calls would overwrite each other. */
  const clearFilters = useCallback(
    (toClear: readonly K[]) =>
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          toClear.forEach((key) => next.delete(key));
          next.delete("page");
          return next;
        },
        { replace: true }
      ),
    [setParams]
  );

  /** Sets several filters in one navigation (an empty string removes one). */
  const setFilters = useCallback(
    (changes: Partial<Record<K, string>>) =>
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          (Object.entries(changes) as Array<[K, string]>).forEach(([key, value]) => (value ? next.set(key, value) : next.delete(key)));
          next.delete("page");
          return next;
        },
        { replace: true }
      ),
    [setParams]
  );

  const hasFilters = keys.some((key) => Boolean(values[key]));

  return { values, page, setFilter, setFilters, setPage, reset, clearFilters, hasFilters };
}

/** Search box state that updates the URL filter after the user pauses typing. */
export function useSearchFilter(current: string, apply: (value: string) => void) {
  const [text, setText] = useState(current);
  const debounced = useDebouncedValue(text.trim());

  useEffect(() => {
    setText((value) => (value.trim() === current ? value : current));
  }, [current]);

  useEffect(() => {
    if (debounced !== current) apply(debounced);
    // Only react to the debounced text.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);

  return [text, setText] as const;
}
