import { describe, expect, it } from "vitest";

import { visibleNavigation } from "../config/navigation";
import { hasAnyPermission, hasPermission, safeRedirectPath } from "./permissions";

describe("permission helpers", () => {
  it("requires every listed permission", () => {
    expect(hasPermission(["a", "b"], "a")).toBe(true);
    expect(hasPermission(["a"], ["a", "b"])).toBe(false);
    expect(hasPermission(undefined, "a")).toBe(false);
    expect(hasAnyPermission(["b"], ["a", "b"])).toBe(true);
  });
});

describe("safeRedirectPath", () => {
  it("keeps in-panel paths for the signed-in channel", () => {
    expect(safeRedirectPath("/admin/merchants?status=ACTIVE", "admin")).toBe("/admin/merchants?status=ACTIVE");
    expect(safeRedirectPath("/merchant/delivery-team", "merchant")).toBe("/merchant/delivery-team");
  });

  it.each([
    ["https://evil.example", "admin", "/admin/dashboard"],
    ["//evil.example/admin", "admin", "/admin/dashboard"],
    ["/\\evil.example", "admin", "/admin/dashboard"],
    ["/merchant/delivery-team", "admin", "/admin/dashboard"],
    ["/admin/users", "merchant", "/merchant/dashboard"],
    ["/administrator", "admin", "/admin/dashboard"],
    [undefined, "merchant", "/merchant/dashboard"]
  ] as const)("rejects %s for %s", (candidate, channel, expected) => {
    expect(safeRedirectPath(candidate, channel)).toBe(expected);
  });
});

describe("visibleNavigation", () => {
  it("never shows Admin modules in the Merchant panel", () => {
    const labels = visibleNavigation("merchant", ["delivery_users.view", "users.view", "merchants.view"])
      .flatMap((section) => section.items)
      .map((item) => item.to);
    expect(labels.every((to) => to.startsWith("/merchant/"))).toBe(true);
    expect(labels).toContain("/merchant/delivery-team");
  });

  it("hides Admin modules the account has no permission for", () => {
    const items = visibleNavigation("admin", ["dashboard.view", "merchants.view"]).flatMap((section) => section.items);
    const paths = items.map((item) => item.to);
    expect(paths).toContain("/admin/merchants");
    expect(paths).not.toContain("/admin/users");
    expect(paths).not.toContain("/admin/audit-logs");
  });

  it("marks modules without a backend as unavailable", () => {
    const items = visibleNavigation("merchant", []).flatMap((section) => section.items);
    expect(items.find((item) => item.to === "/merchant/orders")?.unavailable).toBe(true);
    expect(items.find((item) => item.to === "/merchant/delivery-team")).toBeUndefined();
  });
});
