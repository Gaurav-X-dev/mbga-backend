import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../test/render";
import { AutomationSettings } from "./AutomationSettings";
import { getAutomationSettings, saveAutomationRule, listReminders, type AutomationSettings as Settings, type Rule } from "../../api/reminders.api";

vi.mock("../../auth/auth-context", async original => ({ ...await original<typeof import("../../auth/auth-context")>(), useAuth: () => ({ can: () => true }) }));
vi.mock("../../api/reminders.api", async original => ({ ...await original<typeof import("../../api/reminders.api")>(), getAutomationSettings: vi.fn(), saveAutomationRule: vi.fn(), listReminders: vi.fn() }));
const config: Rule = {
  enabled: false, allowMerchantOverride: false, days: 46, radiusMeters: 7200, maxLocationAgeSeconds: 240,
  maxAccuracyMeters: 80, intervalHours: 17, maxCount: 4, maxSnoozeHours: 100,
  notificationTtlHours: 12, weekdays: [0, 2, 4], startHour: 9, endHour: 20, pushEnabled: true,
  includeNeverOrdered: false, suppressActiveOrders: true,
  customerTypes: [], groupIds: [], staffUserIds: [],
  upcomingDays: 5, missingRates: true, staleReview: true, title: "Dynamic reminder", staffTemplate: "{customer_name}: {reason}", customerTemplate: "Hello {customer_name}"
};
const settings: Settings = { merchantId: null, rules: [{ kind: "PROXIMITY", config, default: config, hasOverride: false, inherited: true }], placeholders: ["customer_name", "reason"], customerTypes: [{ value: "CUSTOM", label: "Custom business" }], groups: [], recipients: [] };
beforeEach(() => {
  vi.clearAllMocks(); vi.mocked(getAutomationSettings).mockResolvedValue(settings);
  vi.mocked(saveAutomationRule).mockResolvedValue(settings);
  vi.mocked(listReminders).mockResolvedValue({ items: [], total: 0 });
});
describe("Dynamic reminder settings", () => {
  it("shows exactly three reminders and the correct message audience without obsolete controls", async () => {
    vi.mocked(getAutomationSettings).mockResolvedValue({ ...settings, rules: (["PROXIMITY", "INACTIVE", "PRICING"] as const).map(kind => ({ kind, config, default: config, hasOverride: false, inherited: true })) });
    const user = userEvent.setup();
    renderWithProviders(<AutomationSettings merchant={false} />);
    await user.click(screen.getByRole("button", { name: /Automated notifications & reminders/ }));
    await screen.findByLabelText("Customer message");
    expect(screen.getAllByRole("tab")).toHaveLength(3);
    expect(screen.queryByLabelText("Merchant message")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Maximum nearby results/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Also remind the customer/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Inactive customer reminder" }));
    expect(screen.getByLabelText("Merchant message")).toBeInTheDocument();
    expect(screen.getByLabelText("Customer message")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Price update reminder" }));
    expect(screen.getByLabelText("Merchant message")).toBeInTheDocument();
    expect(screen.queryByLabelText("Customer message")).not.toBeInTheDocument();
  });

  it("starts collapsed, loads on expansion and preserves unsaved changes when collapsed", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AutomationSettings merchant={false} />);
    const trigger = screen.getByRole("button", { name: /Automated notifications & reminders/ });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(getAutomationSettings).not.toHaveBeenCalled();
    expect(screen.queryByRole("tablist", { name: "Reminder settings" })).not.toBeInTheDocument();
    await user.click(trigger);
    const radius = await screen.findByRole("spinbutton", { name: "Nearby delivery radius (metres)" });
    await user.clear(radius);
    await user.type(radius, "7300");
    await user.click(trigger);
    expect(screen.queryByRole("spinbutton", { name: "Nearby delivery radius (metres)" })).not.toBeInTheDocument();
    await user.click(trigger);
    expect(screen.getByRole("spinbutton", { name: "Nearby delivery radius (metres)" })).toHaveValue(7300);
    expect(saveAutomationRule).not.toHaveBeenCalled();
  });

  it("loads thresholds from the backend and saves only the selected reminder policy", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AutomationSettings merchant={false} />);
    await user.click(screen.getByRole("button", { name: /Automated notifications & reminders/ }));
    expect(await screen.findByLabelText("Nearby delivery radius (metres)")).toHaveValue(7200);
    expect(screen.getByLabelText("Minimum days since last order (0 = any)")).toHaveValue(46);
    await user.click(screen.getByLabelText("Customer types (empty = all)"));
    expect(screen.getByRole("checkbox", { name: "Custom business" })).toBeInTheDocument();
    await user.click(screen.getByLabelText("Enable this reminder"));
    await user.click(screen.getByRole("button", { name: "Save proximity / visit reminder" }));
    await waitFor(() => expect(saveAutomationRule).toHaveBeenCalledWith({ merchant: false, merchantId: undefined }, "PROXIMITY", { ...config, enabled: true }));
  });
  it("keeps merchant overrides read-only when the platform disallows them", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AutomationSettings merchant merchantId={undefined} />);
    await user.click(screen.getByRole("button", { name: /Automated notifications & reminders/ }));
    expect(await screen.findByLabelText("Nearby delivery radius (metres)")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save proximity / visit reminder" })).toBeDisabled();
    expect(screen.getByText(/Platform-managed/)).toBeInTheDocument();
  });
  it("resets a merchant override through the same settings resource", async () => {
    const enabled = { ...config, allowMerchantOverride: true };
    vi.mocked(getAutomationSettings).mockResolvedValue({ ...settings, merchantId: "m1", rules: [{ kind: "PROXIMITY", config: enabled, default: enabled, hasOverride: true, inherited: false }] });
    const user = userEvent.setup();
    renderWithProviders(<AutomationSettings merchant={false} merchantId="m1" />);
    await user.click(screen.getByRole("button", { name: /Automated notifications & reminders/ }));
    await user.click(await screen.findByRole("button", { name: "Use platform default" }));
    await waitFor(() => expect(saveAutomationRule).toHaveBeenCalledWith({ merchant: false, merchantId: "m1" }, "PROXIMITY", null));
  });
});
