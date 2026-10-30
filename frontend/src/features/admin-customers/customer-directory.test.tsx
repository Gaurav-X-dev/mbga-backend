import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../test/render";
import { AdminCustomersPage } from "./AdminCustomersPage";
import { listCustomers, listCustomerEmployees, type Customer } from "../../api/customers.api";
import { downloadCsv } from "../../utils/csv";

vi.mock("../../api/customers.api", async (original) => ({
  ...await original<typeof import("../../api/customers.api")>(), listCustomers: vi.fn(), listCustomerEmployees: vi.fn()
}));
vi.mock("../../api/merchants.api", () => ({listMerchants: vi.fn().mockResolvedValue({items: [{id: "m1", business_name: "Agency"}], total: 1})}));
vi.mock("../../utils/csv", () => ({ downloadCsv: vi.fn() }));
const customer = (id: string) => ({id, businessName: `Store ${id}`, mobile: "9876543210", accountStatus: "ACTIVE", kycStatus: "VERIFIED", runningBalance: 0, deliveryAddress: {}} as Customer);

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listCustomerEmployees).mockResolvedValue([{value: "e1", label: "Alex"}]);
  vi.mocked(listCustomers).mockImplementation(async (params) => ({
    items: [customer("a")], total: 1, limit: params.limit, offset: params.offset
  }));
});

describe("customer directory filters and exports", () => {
  it("passes employee and date range to server and clears them together", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminCustomersPage merchantId="m1" />, "/admin/customer-accounts?employee=e1&dateFrom=2026-10-01&dateTo=2026-10-02");
    await screen.findAllByRole("link", {name: "Store a"});
    expect(listCustomers).toHaveBeenCalledWith(expect.objectContaining({merchantId:"m1", employee:"e1", dateFrom:"2026-10-01", dateTo:"2026-10-02", offset:0}), expect.anything());
    expect(await screen.findByRole("option", {name:"Alex"})).toBeInTheDocument();
    await user.click(screen.getByRole("button", {name:"Clear filters"}));
    await waitFor(() => expect(listCustomers).toHaveBeenLastCalledWith(expect.objectContaining({employee:undefined, dateFrom:undefined, dateTo:undefined}), expect.anything()));
  });
  it("exports all matching pages instead of just the visible page", async () => {
    const user = userEvent.setup();
    vi.mocked(listCustomers).mockImplementation(async (params) => ({
      items: Array.from({length: params.limit === 20 ? 20 : params.offset === 0 ? 100 : 1}, (_, i) => customer(String(params.offset + i))),
      total:101, limit:params.limit, offset:params.offset
    }));
    renderWithProviders(<AdminCustomersPage merchantId="m1" />, "/admin/customer-accounts?employee=e1");
    await screen.findAllByRole("link", {name:"Store 0"});
    await waitFor(() => expect(screen.getByRole("button", {name:"Export report"})).toBeEnabled());
    await user.click(screen.getByRole("button", {name:"Export report"}));
    await waitFor(() => expect(downloadCsv).toHaveBeenCalled());
    expect(vi.mocked(downloadCsv).mock.calls[0][2]).toHaveLength(101);
    expect(listCustomers).toHaveBeenCalledWith(expect.objectContaining({employee:"e1", limit:100, offset:100}));
  });
  it("blocks invalid date ranges and exports", async () => {
    renderWithProviders(<AdminCustomersPage merchantId="m1" />, "/admin/customer-accounts?dateFrom=2026-10-03&dateTo=2026-10-01");
    expect(await screen.findByText("End date must be on or after start date.")).toBeInTheDocument();
    expect(listCustomers).not.toHaveBeenCalled();
    expect(screen.getByRole("button", {name:"Export report"})).toBeDisabled();
  });
});


it("shows GST details and applies GST filters to list and export, then resets", async () => {
  const user = userEvent.setup();
  vi.mocked(listCustomers).mockImplementation(async (params) => ({
    items: [{...customer("gst"), gstin: "27ABCDE1234F1Z5"}, {...customer("blank"), gstin: "   "}],
    total: 2, limit: params.limit, offset: params.offset
  }));
  renderWithProviders(<AdminCustomersPage merchantId="m1" />, "/admin/customer-accounts?page=3");
  expect((await screen.findAllByText("27ABCDE1234F1Z5")).length).toBeGreaterThan(0);
  expect(screen.getAllByText("Non-GST").length).toBeGreaterThan(0);
  await user.selectOptions(screen.getByLabelText("GST Status"), "GST");
  await waitFor(() => expect(listCustomers).toHaveBeenLastCalledWith(expect.objectContaining({gstStatus:"GST", offset:0}), expect.anything()));
  await waitFor(() => expect(screen.getByRole("button", {name:"Export report"})).toBeEnabled());
  await user.click(screen.getByRole("button", {name:"Export report"}));
  await waitFor(() => expect(downloadCsv).toHaveBeenCalled());
  expect(listCustomers).toHaveBeenCalledWith(expect.objectContaining({gstStatus:"GST", limit:100, offset:0}));
  await user.selectOptions(screen.getByLabelText("GST Status"), "NON_GST");
  await waitFor(() => expect(listCustomers).toHaveBeenLastCalledWith(expect.objectContaining({gstStatus:"NON_GST"}), expect.anything()));
  await user.click(screen.getByRole("button", {name:"Clear filters"}));
  await waitFor(() => expect(listCustomers).toHaveBeenLastCalledWith(expect.objectContaining({gstStatus:"ALL"}), expect.anything()));
});
