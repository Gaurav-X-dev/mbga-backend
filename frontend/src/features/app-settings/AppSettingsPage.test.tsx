import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppSettingsPage } from "./AppSettingsPage";
import { getAppSettings, updateAppSettings } from "../../api/app-settings.api";

const context = vi.hoisted(() => ({ channel: "admin", manage: true, toast: vi.fn() }));
vi.mock("../../auth/auth-context", () => ({ useAuth: () => ({ channel: context.channel,
  can: (permission: string) => ["platform_settings.view", "delivery.view"].includes(permission) ||
    context.manage && ["platform_settings.manage", "delivery.confirm"].includes(permission) }) }));
vi.mock("../../components/feedback/toast-context", () => ({ useToast: () => ({ success: context.toast }) }));
vi.mock("../../api/app-settings.api", async (original) => ({ ...await original<typeof import("../../api/app-settings.api")>(),
  getAppSettings: vi.fn(), updateAppSettings: vi.fn() }));

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter><AppSettingsPage /></MemoryRouter></QueryClientProvider>);
}
const global = { deliveryRadiusMeters: 300, deliveryRadiusKm: 0.3, orderCutoffHour: 16 };
beforeEach(() => { vi.clearAllMocks(); context.channel = "admin"; context.manage = true;
  vi.mocked(getAppSettings).mockResolvedValue(global);
  vi.mocked(updateAppSettings).mockResolvedValue({ ...global, deliveryRadiusMeters: 500, deliveryRadiusKm: 0.5 });
});

describe("App Settings", () => {
  it("shows km and saves only the changed global radius", async () => {
    mount(); const user = userEvent.setup();
    const input = await screen.findByLabelText(/Arrival radius/);
    expect(screen.getByText(/0.3 km allowed/)).toBeInTheDocument();
    await user.clear(input); await user.type(input, "500");
    await user.click(screen.getByRole("button", { name: "Save radius" }));
    await waitFor(() => expect(updateAppSettings).toHaveBeenCalledWith("/admin/settings", { deliveryRadiusMeters: 500 }));
  });
  it("resets merchant override without changing platform settings", async () => {
    context.channel = "merchant";
    vi.mocked(getAppSettings).mockResolvedValue({ deliveryRadiusMeters: 600, deliveryRadiusKm: 0.6,
      overrideRadiusMeters: 600, defaultRadiusMeters: 300, merchantId: "agency" });
    mount(); const user = userEvent.setup();
    await user.click(await screen.findByLabelText(/Use platform default/));
    expect(screen.getByLabelText(/Arrival radius/)).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Save radius" }));
    await waitFor(() => expect(updateAppSettings).toHaveBeenCalledWith("/merchant/settings", { deliveryRadiusMeters: null }));
    expect(screen.queryByText("Order scheduling")).not.toBeInTheDocument();
  });
  it("does not allow read-only users to save settings", async () => {
    context.manage = false; mount();
    expect(await screen.findByLabelText(/Arrival radius/)).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save radius" })).not.toBeInTheDocument();
    expect(updateAppSettings).not.toHaveBeenCalled();
  });
});
