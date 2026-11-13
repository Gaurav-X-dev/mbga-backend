import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as pricingApiModule from "../../api/competitor-pricing.api";
import { listMerchants } from "../../api/merchants.api";
import { visibleNavigation } from "../../config/navigation";
import { AdminCompetitorPricingPage } from "./AdminCompetitorPricingPage";
import { competitorPricingApi as api } from "../../api/competitor-pricing.api";
import { AppError } from "../../api/errors";
import type { Address } from "../../api/orders.api";
import { today } from "./market-options";
import { CompetitorPricingPage } from "./CompetitorPricingPage";

const state = vi.hoisted(() => ({ permissions: ["pricing.view", "pricing.manage", "competitor_pricing.manage", "competitor_pricing.record"] }));
vi.mock("../../components/maps/GoogleMapLocationPicker", () => ({ GoogleMapLocationPicker: ({ onChange }: { onChange: (value: Address) => void }) => <button type="button" onClick={() => onChange({ line1: "Depot 42", city: "Gurugram", state: "Haryana", pincode: "122001", latitude: 28.4595, longitude: 77.0266 })}>Pin depot</button> }));
vi.mock("../../api/merchants.api", () => ({ listMerchants: vi.fn() }));
vi.mock("../../auth/auth-context", () => ({ useAuth: () => ({ user: { user_id: "staff", merchant: { id: "merchant-1" } }, can: (permission: string) => state.permissions.includes(permission) }) }));
vi.mock("../../api/locations.api", () => ({ lookupPincode: vi.fn().mockResolvedValue({ pincode: "110001", district: "Delhi", state: "Delhi", serviceable: true, offices: [{ officeName: "Central Delhi" }] }) }));
vi.mock("../../components/feedback/toast-context", () => ({ useToast: () => ({ success: vi.fn() }) }));
const brand = { id: "brand-1", name: "Bharat Gas", code: "BHARATGAS", color: "#F97316", iconName: "flame", status: "ACTIVE" as const, notes: null, updatedAt: "2026-10-30T06:30:00Z" };
const base = { competitorId: "mbga_self", name: "MBGA (Your Price)", price: 1850, difference: 0, differencePercentage: 0, isMbga: true, color: "#2563EB", iconName: "flame", updatedAt: brand.updatedAt, updatedBy: "Manager", updatedByRole: null };

beforeEach(() => {
  vi.restoreAllMocks();
  state.permissions = ["pricing.view", "pricing.manage", "competitor_pricing.manage", "competitor_pricing.record"];
  vi.spyOn(api, "brands").mockResolvedValue([brand]);
  vi.spyOn(api, "comparison").mockResolvedValue([base]);
  vi.spyOn(api, "snapshot").mockResolvedValue({ cylinderType: "19 kg", cylinderLabel: "19 kg", mbgaPrice: 1850, avgCompetitorPrice: 1925, difference: 75, differencePercentage: 3.9, isLower: true });
  vi.spyOn(api, "history").mockResolvedValue([]);
  vi.spyOn(api, "audit").mockResolvedValue([]);
  vi.spyOn(api, "survey").mockResolvedValue({ success: true });
  vi.spyOn(api, "benchmark").mockResolvedValue({ success: true, mbgaPrice: 1880 });
  vi.spyOn(api, "createBrand").mockResolvedValue(brand);
  vi.spyOn(api, "updateDepot").mockResolvedValue(brand);
  vi.spyOn(api, "exportReport").mockResolvedValue(undefined);
});
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><CompetitorPricingPage /></QueryClientProvider>);
  return userEvent.setup();
}
async function selectMarket(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Delivery pincode"), "110001");
  await screen.findByText("Market comparison");
}

describe("competitor pricing", () => {
  it("waits for a valid pincode and labels the no-quotes fallback", async () => {
    const user = setup();
    expect(api.snapshot).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Record survey" })).toBeDisabled();
    await selectMarket(user);
    expect(api.comparison).toHaveBeenCalledWith({ pincode: "110001", customerType: "Retail (Domestic)", cylinderType: "LPG_19KG" }, expect.anything());
    expect(screen.getByText(/market average is an estimate/)).toBeInTheDocument();
  });

  it("saves a survey using the selected dimensions and refreshes comparisons", async () => {
    const user = setup();
    await selectMarket(user);
    const before = vi.mocked(api.comparison).mock.calls.length;
    await user.click(screen.getByRole("button", { name: "Record survey" }));
    const dialog = within(screen.getByRole("dialog"));
    await user.selectOptions(dialog.getByRole("combobox", { name: "Competitor" }), brand.id);
    await user.type(dialog.getByRole("spinbutton", { name: "Selling price (₹)" }), "1950");
    await user.type(dialog.getByLabelText(/Notes/), "Invoice verified");
    await user.click(dialog.getByRole("button", { name: "Save rate" }));
    await waitFor(() => expect(api.survey).toHaveBeenCalledWith(expect.objectContaining({ competitorId: brand.id, cylinderType: "LPG_19KG", locationPincode: "110001", customerType: "Retail (Domestic)", price: 1950, notes: "Invoice verified" })));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(vi.mocked(api.comparison).mock.calls.length).toBeGreaterThan(before));
  });

  it("keeps the MBGA benchmark read only", async () => {
    setup();
    await selectMarket(userEvent.setup());
    const mbgaRow = screen.getByText("MBGA (Your Price)").closest("tr")!;
    expect(within(mbgaRow).queryByRole("button", { name: "Edit rate" })).not.toBeInTheDocument();
    expect(api.benchmark).not.toHaveBeenCalled();
  });

  it("hides write controls for read-only users and handles restricted audit access", async () => {
    state.permissions = ["pricing.view"];
    vi.mocked(api.audit).mockRejectedValue(new AppError({ kind: "forbidden", status: 403, userMessage: "Audit access is restricted to office staff." }));
    const user = setup();
    expect(screen.queryByRole("button", { name: "Record survey" })).not.toBeInTheDocument();
    await selectMarket(user);
    expect(screen.queryByRole("button", { name: "Edit rate" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Competitors" }));
    expect(screen.queryByRole("button", { name: "Add competitor" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Recent changes" }));
    expect(await screen.findByText("Audit access is restricted to office staff.")).toBeInTheDocument();
  });

  it("registers a competitor without client-supplied identity fields", async () => {
    const user = setup();
    await user.click(screen.getByRole("tab", { name: "Competitors" }));
    await user.click(screen.getByRole("button", { name: "Add competitor" }));
    const dialog = within(screen.getByRole("dialog"));
    await user.type(dialog.getByRole("textbox", { name: "Competitor name" }), "Regional LPG");
    await user.click(dialog.getByRole("button", { name: "Save competitor" }));
    await waitFor(() => expect(api.createBrand).toHaveBeenCalledWith({ name: "Regional LPG", color: "#8B5CF6", notes: "" }));
  });
});

it("requests history for the selected market, timeframe, and vapor cylinder", async () => {
  const user = setup();
  await selectMarket(user);
  await user.selectOptions(screen.getByLabelText("Cylinder size"), "LPG_47_5KG_V");
  await user.click(screen.getByRole("tab", { name: "Trends" }));
  await screen.findByText("No price observations yet");
  await user.selectOptions(screen.getByLabelText("History timeframe"), "1Y");
  await waitFor(() => expect(api.history).toHaveBeenLastCalledWith({ pincode: "110001", customerType: "Retail (Domestic)", cylinderType: "LPG_47_5KG_V", timeframe: "1Y" }, expect.anything()));
});

it("confirms competitor inactivation and refreshes the directory", async () => {
  vi.spyOn(api, "status").mockResolvedValue({ ...brand, status: "INACTIVE" });
  const user = setup();
  await user.click(screen.getByRole("tab", { name: "Competitors" }));
  await user.click(await screen.findByRole("button", { name: "Inactivate" }));
  expect(api.status).not.toHaveBeenCalled();
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Inactivate" }));
  await waitFor(() => expect(api.status).toHaveBeenCalledWith(brand.id, "INACTIVE"));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
});

it("uses custom dates for history and shares the same scoped export parameters", async () => {
  const user = setup();
  await selectMarket(user);
  await user.click(screen.getByRole("tab", { name: "Trends" }));
  await user.selectOptions(screen.getByLabelText("History timeframe"), "CUSTOM");
  expect(vi.mocked(api.history).mock.calls.some(([params]) => params.timeframe === "CUSTOM")).toBe(false);
  const start = new Date(`${today()}T00:00:00Z`); start.setUTCDate(start.getUTCDate() - 3);
  const startDate = start.toISOString().slice(0, 10);
  fireEvent.change(screen.getByLabelText("History start date"), { target: { value: startDate } });
  await waitFor(() => expect(api.history).toHaveBeenLastCalledWith(expect.objectContaining({ timeframe: "CUSTOM", startDate, endDate: today(), pincode: "110001" }), expect.anything()));
  await user.click(screen.getByRole("button", { name: "Export report" }));
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Download report" }));
  await waitFor(() => expect(api.exportReport).toHaveBeenCalledWith(expect.objectContaining({ pincode: "110001", cylinderType: "LPG_19KG", timeframe: "CUSTOM", startDate, endDate: today(), format: "XLSX", includeAudit: false })));
});

it("retries only the survey when combined registration partially succeeds", async () => {
  vi.mocked(api.survey).mockRejectedValueOnce(new AppError({ kind: "network", userMessage: "Rate save failed. Retry." })).mockResolvedValueOnce({ success: true });
  const user = setup();
  await selectMarket(user);
  await user.click(screen.getByRole("tab", { name: "Competitors" }));
  await user.click(screen.getByRole("button", { name: "Add competitor" }));
  const dialog = within(screen.getByRole("dialog"));
  await user.type(dialog.getByRole("textbox", { name: "Competitor name" }), "Regional LPG");
  await user.click(dialog.getByRole("checkbox", { name: "Also record initial rate" }));
  await user.type(dialog.getByRole("spinbutton", { name: "Selling price (₹)" }), "1950");
  await user.click(dialog.getByRole("button", { name: "Save competitor" }));
  await dialog.findByText("Rate save failed. Retry.");
  expect(api.createBrand).toHaveBeenCalledTimes(1);
  await user.click(dialog.getByRole("button", { name: "Retry rate save" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(api.createBrand).toHaveBeenCalledTimes(1);
  expect(api.survey).toHaveBeenCalledTimes(2);
});

it("requires explicit existing-brand selection after a duplicate conflict", async () => {
  vi.mocked(api.createBrand).mockRejectedValue(new AppError({ kind: "conflict", status: 409, userMessage: "Duplicate competitor code" }));
  const user = setup();
  await selectMarket(user);
  await user.click(screen.getByRole("tab", { name: "Competitors" }));
  await user.click(screen.getByRole("button", { name: "Add competitor" }));
  const dialog = within(screen.getByRole("dialog"));
  await user.type(dialog.getByRole("textbox", { name: "Competitor name" }), "Bharat Gas");
  await user.click(dialog.getByRole("checkbox", { name: "Also record initial rate" }));
  await user.type(dialog.getByRole("spinbutton", { name: "Selling price (₹)" }), "1950");
  await user.click(dialog.getByRole("button", { name: "Save competitor" }));
  await dialog.findByLabelText("Use existing competitor");
  expect(api.survey).not.toHaveBeenCalled();
  await user.selectOptions(dialog.getByLabelText("Use existing competitor"), brand.id);
  await user.click(dialog.getByRole("button", { name: "Save competitor" }));
  await waitFor(() => expect(api.survey).toHaveBeenCalledWith(expect.objectContaining({ competitorId: brand.id, price: 1950 })));
  expect(api.createBrand).toHaveBeenCalledTimes(1);
});

it("reuses the depot picker and persists structured coordinates", async () => {
  const user = setup();
  await user.click(screen.getByRole("tab", { name: "Competitors" }));
  await user.click(await screen.findByRole("button", { name: "Edit depot" }));
  const dialog = within(screen.getByRole("dialog"));
  await user.click(dialog.getByRole("button", { name: "Choose depot on map" }));
  await user.click(dialog.getByRole("button", { name: "Pin depot" }));
  await user.click(dialog.getByRole("button", { name: "Save depot" }));
  await waitFor(() => expect(api.updateDepot).toHaveBeenCalledWith(brand.id, expect.objectContaining({ line1: "Depot 42", pincode: "122001", latitude: 28.4595, longitude: 77.0266 }), ""));
});

it("sends audit pincode, segment, and recorded-date filters to the existing API", async () => {
  const user = setup();
  await user.click(screen.getByRole("tab", { name: "Recent changes" }));
  await user.type(screen.getByLabelText("Audit pincode"), "122001");
  await user.selectOptions(screen.getByLabelText("Audit segment"), "Commercial (Industrial)");
  fireEvent.change(screen.getByLabelText("Audit start date"), { target: { value: today() } });
  fireEvent.change(screen.getByLabelText("Audit end date"), { target: { value: today() } });
  await waitFor(() => expect(api.audit).toHaveBeenLastCalledWith(expect.objectContaining({ pincode: "122001", customerType: "Commercial (Industrial)", startDate: today(), endDate: today(), limit: 20, offset: 0 }), expect.anything()));
});

it("shows the admin navigation entry only with merchant and pricing read permissions", () => {
  const path = "/admin/competitor-pricing";
  const links = (permissions: string[]) => visibleNavigation("admin", permissions).flatMap(section => section.items.map(item => item.to));
  expect(links(["merchants.view", "pricing.view"])).toContain(path);
  expect(links(["pricing.view"])).not.toContain(path);
  expect(links(["merchants.view"])).not.toContain(path);
});

it("waits for explicit merchant selection and resets pricing state on an admin merchant switch", async () => {
  vi.mocked(listMerchants).mockResolvedValue({ items: [
    { id: "merchant-one", business_name: "Agency One", merchant_code: "ONE" },
    { id: "merchant-two", business_name: "Agency Two", merchant_code: "TWO" }
  ], total: 2, limit: 100, offset: 0 } as Awaited<ReturnType<typeof listMerchants>>);
  const one = { ...api, brands: vi.fn().mockResolvedValue([brand]), comparison: vi.fn().mockResolvedValue([base]), snapshot: vi.fn().mockResolvedValue({ mbgaPrice: 1850, avgCompetitorPrice: 1925, difference: 75, differencePercentage: 3.9, isLower: true }) };
  const two = { ...api, brands: vi.fn().mockResolvedValue([]), comparison: vi.fn().mockResolvedValue([base]) };
  const factory = vi.spyOn(pricingApiModule, "createCompetitorPricingApi").mockImplementation(id => id === "merchant-one" ? one : two);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><AdminCompetitorPricingPage /></QueryClientProvider>);
  const user = userEvent.setup();
  await screen.findByRole("option", { name: "Agency One (ONE)" });
  expect(one.brands).not.toHaveBeenCalled();
  await user.selectOptions(screen.getByRole("combobox", { name: "Select merchant" }), "merchant-one");
  await waitFor(() => expect(one.brands).toHaveBeenCalled());
  await selectMarket(user);
  await user.click(screen.getByRole("tab", { name: "Competitors" }));
  await screen.findByText("Bharat Gas");
  await user.selectOptions(screen.getByRole("combobox", { name: "Select merchant" }), "merchant-two");
  await waitFor(() => expect(two.brands).toHaveBeenCalled());
  expect(screen.getByLabelText("Delivery pincode")).toHaveValue("");
  expect(screen.queryByText("Bharat Gas")).not.toBeInTheDocument();
  expect(two.comparison).not.toHaveBeenCalled();
  expect(factory).toHaveBeenCalledWith("merchant-two");
});
