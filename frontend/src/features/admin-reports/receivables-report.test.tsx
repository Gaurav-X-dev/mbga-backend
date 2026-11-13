import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../test/render";
import { AdminReportsPage } from "./AdminReportsPage";
import { getReceivables, getReceivableDetail, exportReceivables } from "../../api/receivables.api";
import type { Report } from "../../api/reports.api";

vi.mock("../../auth/auth-context", async original => ({
  ...await original<typeof import("../../auth/auth-context")>(),
  useOptionalAuth: () => ({ user: { user_id: "admin" }, can: () => true })
}));
vi.mock("../../api/receivables.api", async original => ({
  ...await original<typeof import("../../api/receivables.api")>(),
  getReceivables: vi.fn(), getReceivableDetail: vi.fn(), exportReceivables: vi.fn(),
  listReportGroups: vi.fn().mockResolvedValue([{ id: "g1", merchantId: "m1", name: "Hotels", active: true }])
}));
vi.mock("../../api/merchants.api", () => ({ listMerchants: vi.fn().mockResolvedValue({ items: [{ id: "m1", business_name: "Agency" }], total: 1 }) }));
const report: Report = {
  type: "OUTSTANDING_DUES", title: "Outstanding Dues", period: { from: "2026-11-02T00:00:00+05:30", to: "2026-11-02T12:00:00+05:30" },
  generatedAt: "2026-11-02T12:00:00+05:30", summary: [{ label: "Outstanding amount", value: 5000 }],
  columns: [{ key: "customer", label: "Customer" }, { key: "outstanding", label: "Outstanding amount" }],
  rows: [{ id: "m1:c1", customerId: "c1", merchantId: "m1", customer: "Hotel One", outstanding: 1500 }], metadata: { total: 51 }
};
beforeEach(() => {
  vi.clearAllMocks(); window.localStorage.clear();
  vi.mocked(getReceivables).mockResolvedValue(report);
  vi.mocked(getReceivableDetail).mockResolvedValue({ total: 1, rows: [{ id: "i1", invoice: "INV-1", amount: 2000, appliedAmount: 500, balance: 1500,
    _details: { title: "INV-1", fields: [{ label: "Outstanding amount", value: 1500 }] } }] });
  vi.mocked(exportReceivables).mockResolvedValue("dues.xlsx");
});

describe("Admin receivables reports", () => {
  it("uses server totals, drills into invoices, paginates and exports the same filters", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdminReportsPage />, "/admin/reports?type=OUTSTANDING_DUES&merchant=m1&group=g1&overdue=true");
    await screen.findAllByRole("button", { name: "Hotel One" });
    expect(getReceivables).toHaveBeenCalledWith(expect.objectContaining({ type: "OUTSTANDING_DUES", merchantId: "m1", groupId: "g1", overdueOnly: true, offset: 0, limit: 25 }), expect.anything());
    expect(screen.getByLabelText("Report summary")).toHaveTextContent("5,000");
    await user.click(screen.getAllByRole("button", { name: "Hotel One" })[0]);
    await screen.findAllByRole("button", { name: "INV-1" });
    expect(getReceivableDetail).toHaveBeenCalledWith(expect.objectContaining({ merchantId: "m1", customerId: "c1" }), expect.anything());
    await user.click(screen.getByRole("button", { name: "Close" }));
    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(getReceivables).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 25 }), expect.anything()));
    await user.click(screen.getByRole("button", { name: "Export" }));
    await waitFor(() => expect(exportReceivables).toHaveBeenCalledWith(expect.objectContaining({ merchantId: "m1", groupId: "g1", overdueOnly: true }), "XLSX"));
  });
  it("keeps an explicit all-merchants selection after clearing a remembered merchant", async () => {
    window.localStorage.setItem("mbga.web.selected-merchant", "m1");
    const user = userEvent.setup();
    renderWithProviders(<AdminReportsPage />, "/admin/reports?type=OUTSTANDING_DUES");
    await screen.findAllByRole("button", { name: "Hotel One" });
    await user.selectOptions(screen.getByLabelText("Merchant"), "");
    await waitFor(() => expect(getReceivables).toHaveBeenLastCalledWith(expect.objectContaining({ merchantId: undefined }), expect.anything()));
    expect(window.localStorage.getItem("mbga.web.selected-merchant")).toBeNull();
  });

  it("drills from a merchant group to customers while retaining collection filters", async () => {
    vi.mocked(getReceivables).mockResolvedValue({ ...report, type: "CUSTOMER_COLLECTION", columns: [{ key: "group", label: "Group" }], rows: [{ id: "m1:g1", merchantId: "m1", groupId: "g1", group: "Hotels" }] });
    const user = userEvent.setup();
    renderWithProviders(<AdminReportsPage />, "/admin/reports?type=CUSTOMER_COLLECTION&groupBy=group&mode=UPI&status=PENDING&dateFrom=2026-10-01&dateTo=2026-10-31");
    await user.click((await screen.findAllByRole("button", { name: "Hotels" }))[0]);
    await waitFor(() => expect(getReceivables).toHaveBeenLastCalledWith(expect.objectContaining({ merchantId: "m1", groupId: "g1", groupBy: "customer", mode: "UPI", status: "PENDING", dateFrom: "2026-10-01", dateTo: "2026-10-31" }), expect.anything()));
  });
});
