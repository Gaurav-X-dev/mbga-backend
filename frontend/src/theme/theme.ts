/**
 * Light/dark theme, resolved to a concrete value before the first paint.
 *
 * The stylesheet only ever reads `[data-theme="dark"]`, never `prefers-color-scheme`, so
 * "follow the system" is resolved here instead of in CSS. That keeps one dark palette in the
 * stylesheet rather than two copies, and lets a person's explicit choice win over the OS.
 */
export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "mbga.web.theme";

function systemTheme(): ResolvedTheme {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function readThemePreference(): ThemePreference {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch {
    // Private mode or blocked storage: fall back to the system setting.
  }
  return "system";
}

export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  return preference === "system" ? systemTheme() : preference;
}

/** Writes the resolved theme where CSS can see it, and tells the browser about form controls. */
export function applyTheme(preference: ThemePreference): ResolvedTheme {
  const resolved = resolveTheme(preference);
  const root = document.documentElement;
  root.dataset.theme = resolved;
  root.style.colorScheme = resolved;
  return resolved;
}

export function storeThemePreference(preference: ThemePreference) {
  try {
    window.localStorage.setItem(STORAGE_KEY, preference);
  } catch {
    // Preference only; the theme still applies for this session.
  }
}

/** Calls back when the OS theme changes, but only while the preference is "system". */
export function watchSystemTheme(onChange: () => void): () => void {
  const query = window.matchMedia?.("(prefers-color-scheme: dark)");
  if (!query) return () => undefined;
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}
