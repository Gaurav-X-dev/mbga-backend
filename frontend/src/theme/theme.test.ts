import { afterEach, describe, expect, it, vi } from "vitest";

import { applyTheme, readThemePreference, resolveTheme, storeThemePreference } from "./theme";

function mockSystemPrefersDark(dark: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: dark && query.includes("dark"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn()
    }))
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("theme preference", () => {
  it("falls back to the system setting when nothing is stored", () => {
    expect(readThemePreference()).toBe("system");
  });

  it("reads back a stored choice and ignores anything else", () => {
    storeThemePreference("dark");
    expect(readThemePreference()).toBe("dark");
    window.localStorage.setItem("mbga.web.theme", "chartreuse");
    expect(readThemePreference()).toBe("system");
  });

  it("resolves 'system' from the OS, and an explicit choice overrides it", () => {
    mockSystemPrefersDark(true);
    expect(resolveTheme("system")).toBe("dark");
    expect(resolveTheme("light")).toBe("light");

    mockSystemPrefersDark(false);
    expect(resolveTheme("system")).toBe("light");
    expect(resolveTheme("dark")).toBe("dark");
  });

  it("writes the resolved theme where CSS and the browser can see it", () => {
    mockSystemPrefersDark(true);
    expect(applyTheme("system")).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.style.colorScheme).toBe("dark");

    expect(applyTheme("light")).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.style.colorScheme).toBe("light");
  });
});
