import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useDebouncedValue } from "./useDebouncedValue";

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
    return result;
    // keys is a static list per page
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);

  const setFilter = useCallback(
    (key: K, value: string) => {
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

  const hasFilters = keys.some((key) => Boolean(values[key]));

  return { values, page, setFilter, setPage, reset, hasFilters };
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
