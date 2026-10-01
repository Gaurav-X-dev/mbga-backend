import { createContext, useContext } from "react";

import type { ResolvedTheme, ThemePreference } from "./theme";

export type ThemeContextValue = {
  /** What the person chose: an explicit theme, or "system". */
  preference: ThemePreference;
  /** What is actually on screen right now. */
  theme: ResolvedTheme;
  setPreference: (preference: ThemePreference) => void;
  /** Flips between light and dark, leaving "system" behind. */
  toggle: () => void;
};

export const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used inside ThemeProvider");
  return context;
}
