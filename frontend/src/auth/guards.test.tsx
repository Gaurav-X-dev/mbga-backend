import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { PermissionGuard } from "./PermissionGuard";
import { tokenStorage } from "./token-storage";
import { createFakeBackend, installFakeBackend, uninstallFakeBackend, type FakeBackend } from "../test/fake-backend";
import { renderApp, renderWithProviders } from "../test/render";

/** Signs in against the fake backend without going through the UI. */
async function seedSession(backend: FakeBackend, channel: "admin" | "merchant", mobile: string) {
  const { apiClient } = await import("../api/client");
  const { data: challenge } = await apiClient.post(`/${channel}/auth/otp/request`, { mobile_number: mobile });
  const { data } = await apiClient.post(`/${channel}/auth/otp/verify`, { request_id: challenge.request_id, otp: "1234" });
  tokenStorage.set({ channel, accessToken: data.token.access_token, refreshToken: data.token.refresh_token });
  return backend;
}

describe("route protection", () => {
  let backend: FakeBackend;
  beforeEach(() => {
    backend = createFakeBackend();
    installFakeBackend(backend);
  });
  afterEach(() => uninstallFakeBackend());

  it("sends signed-out visitors to sign in and remembers where they were going", async () => {
    const { router } = renderApp("/admin/merchants?status=ACTIVE");
    expect(await screen.findByRole("heading", { name: "Welcome to MBGA" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/login");
    expect(router.state.location.state).toEqual({ from: "/admin/merchants?status=ACTIVE" });
    // The destination is in the Admin panel, so Admin is preselected.
    expect(screen.getByRole("radio", { name: "Admin panel" })).toBeChecked();
  });

  it("refuses to open Admin pages with a Merchant session", async () => {
    backend.addUser({
      mobile: "+919000000002",
      name: "Meena Merchant",
      status: "ACTIVE",
      channels: { MERCHANT: ["delivery_users.view"] },
      roles: ["manager"]
    });
    await seedSession(backend, "merchant", "+919000000002");
    renderApp("/admin/merchants");
    expect(await screen.findByRole("heading", { name: "This area is not part of your panel" })).toBeInTheDocument();
    expect(backend.calls).not.toContain("GET /admin/merchants");
    expect(backend.calls.some((call) => call.startsWith("GET /admin/"))).toBe(false);
  });

  it("refuses to open Merchant pages with an Admin session", async () => {
    await seedSession(backend, "admin", "+919999900001");
    renderApp("/merchant/delivery-team");
    expect(await screen.findByRole("heading", { name: "This area is not part of your panel" })).toBeInTheDocument();
    expect(backend.calls.some((call) => call.startsWith("GET /merchant/"))).toBe(false);
  });

  it("shows access denied inside the panel when a permission is missing", async () => {
    backend.addUser({
      mobile: "+919000000003",
      name: "Limited Admin",
      status: "ACTIVE",
      channels: { ADMIN: ["dashboard.view"] },
      roles: ["support"]
    });
    await seedSession(backend, "admin", "+919000000003");
    renderApp("/admin/users");
    expect(await screen.findByRole("heading", { name: "You don’t have access to this page" })).toBeInTheDocument();
    // Navigation only lists modules the account can use.
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(nav).toHaveTextContent("Dashboard");
    expect(nav).not.toHaveTextContent("Users");
    expect(nav).not.toHaveTextContent("Merchants");
  });

  it("redirects to sign in with a notice when the session can no longer be renewed", async () => {
    await seedSession(backend, "admin", "+919999900001");
    backend.revokeAllSessions();
    const { router } = renderApp("/admin/dashboard");
    expect(await screen.findByText("Your session has ended. Please sign in again.")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/login");
    expect(tokenStorage.get()).toBeNull();
  });

  it("renews an expired access token once and continues", async () => {
    await seedSession(backend, "admin", "+919999900001");
    const before = tokenStorage.get();
    backend.expireAccessTokens();
    renderApp("/admin/dashboard");
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    await waitFor(() => expect(tokenStorage.get()?.accessToken).not.toBe(before?.accessToken));
    expect(backend.calls.filter((call) => call === "POST /admin/auth/token/refresh")).toHaveLength(1);
  });

  it("shows a friendly page when the server cannot be reached", async () => {
    await seedSession(backend, "admin", "+919999900001");
    backend.options.failNetwork = true;
    renderApp("/admin/dashboard");
    expect(await screen.findByRole("heading", { name: "The service is temporarily unavailable" }, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.getByText("We could not connect to the server. Check your connection and try again.")).toBeInTheDocument();
    // A connectivity problem must not sign the user out.
    expect(tokenStorage.get()).not.toBeNull();
  }, 15000);

  it("PermissionGuard hides content without the permission", async () => {
    await seedSession(backend, "admin", "+919999900001");
    renderWithProviders(
      <>
        <PermissionGuard permission="merchants.create">
          <button>Add merchant</button>
        </PermissionGuard>
        <PermissionGuard permission="roles.delete" fallback={<span>No delete access</span>}>
          <button>Delete role</button>
        </PermissionGuard>
      </>
    );
    expect(await screen.findByRole("button", { name: "Add merchant" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete role" })).not.toBeInTheDocument();
    expect(screen.getByText("No delete access")).toBeInTheDocument();
  });
});
