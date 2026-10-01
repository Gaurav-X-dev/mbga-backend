import { useCallback, useEffect, useMemo, useState } from "react";
import type { PropsWithChildren } from "react";

import { ThemeContext, type ThemeContextValue } from "./theme-context";
import {
  applyTheme,
  readThemePreference,
  resolveTheme,
  storeThemePreference,
  watchSystemTheme,
  type ResolvedTheme,
  type ThemePreference
} from "./theme";

export function ThemeProvider({ children }: PropsWithChildren) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readThemePreference);
  const [theme, setTheme] = useState<ResolvedTheme>(() => resolveTheme(readThemePreference()));

  useEffect(() => {
    setTheme(applyTheme(preference));
  }, [preference]);

  // Only follow the OS while the person has not picked a side.
  useEffect(() => {
    if (preference !== "system") return;
    return watchSystemTheme(() => setTheme(applyTheme("system")));
  }, [preference]);

  const setPreference = useCallback((next: ThemePreference) => {
    storeThemePreference(next);
    setPreferenceState(next);
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({
      preference,
      theme,
      setPreference,
      toggle: () => setPreference(theme === "dark" ? "light" : "dark")
    }),
    [preference, theme, setPreference]
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
