import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getKycApplication, revealDocumentNumber } from "../../api/customer-kyc.api";
import { CustomerKycDetailPage } from "./CustomerKycDetailPage";

const state = vi.hoisted(() => ({ role: "super_admin", verify: true }));
vi.mock("../../auth/auth-context", async (original) => ({ ...await original<typeof import("../../auth/auth-context")>(),
  useOptionalAuth: () => ({ channel: "admin", user: { user_id: "reviewer", active_roles: [state.role] },
    can: (permission: string) => permission !== "customers.verify" || state.verify }) }));
vi.mock("../../api/customer-kyc.api", async (original) => ({ ...await original<typeof import("../../api/customer-kyc.api")>(),
  getKycApplication: vi.fn(), revealDocumentNumber: vi.fn() }));
vi.mock("./CustomerOrdersCard", () => ({ CustomerOrdersCard: () => null }));
vi.mock("./KycDecisionDialogs", () => ({ KycDecisionDialogs: () => null }));
const docs = [
  { id: "gst-id", type: "GST", numberMasked: "06XXXXXXXXXX1Z1", fileId: "gst-file", status: "UPLOADED" },
  { id: "pan-id", type: "PAN", numberMasked: "XXXXX1540C", fileId: "pan-file", status: "UPLOADED" }
];
beforeEach(() => {
  vi.clearAllMocks(); state.role = "super_admin"; state.verify = true;
  vi.mocked(getKycApplication).mockResolvedValue({ id: "application", customerId: "customer", mobile: "9876543210",
    status: "APPROVED", deliveryAddress: {}, submittedAt: "2026-10-29T00:00:00Z", documents: docs });
  vi.mocked(revealDocumentNumber).mockImplementation(async (_application, id) => ({ documentId: id,
    documentType: id === "gst-id" ? "GST" : "PAN", number: id === "gst-id" ? "06ABCDE1234F1Z1" : "ABCDE1540C",
    numberMasked: docs.find(document => document.id === id)!.numberMasked }));
});
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/admin/customers/application?merchant=merchant"]}>
    <Routes><Route path="/admin/customers/:applicationId" element={<CustomerKycDetailPage />} /></Routes>
  </MemoryRouter></QueryClientProvider>);
}
describe("KYC queue document number reveal", () => {
  it("loads the full ID using the document ID and removes it when hidden", async () => {
    mount(); const user = userEvent.setup();
    const buttons = await screen.findAllByRole("button", { name: "Show number" });
    expect(revealDocumentNumber).not.toHaveBeenCalled();
    await user.click(buttons[0]);
    expect(await screen.findByText("06ABCDE1234F1Z1")).toBeInTheDocument();
    expect(revealDocumentNumber).toHaveBeenCalledWith("application", "gst-id");
    await user.click(screen.getByRole("button", { name: "Hide number" }));
    expect(screen.queryByText("06ABCDE1234F1Z1")).not.toBeInTheDocument();
  });
  it("shows all full IDs and refetches after Hide all", async () => {
    mount(); const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Show all numbers" }));
    expect(await screen.findByText("06ABCDE1234F1Z1")).toBeInTheDocument();
    expect(await screen.findByText("ABCDE1540C")).toBeInTheDocument();
    expect(revealDocumentNumber).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole("button", { name: "Hide all numbers" }));
    expect(screen.queryByText("ABCDE1540C")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show all numbers" }));
    await waitFor(() => expect(revealDocumentNumber).toHaveBeenCalledTimes(4));
  });
  it.each(["admin", "super_admin_without_verify"])("preserves masking without full-number access: %s", async (role) => {
    state.role = role === "admin" ? "admin" : "super_admin"; state.verify = role === "admin";
    mount(); const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Show all numbers" }));
    expect(screen.getByText("XXXXX1540C")).toBeInTheDocument();
    expect(screen.queryByText("ABCDE1540C")).not.toBeInTheDocument();
    expect(revealDocumentNumber).not.toHaveBeenCalled();
  });
  it("shows reveal errors instead of treating a masked ID as revealed", async () => {
    vi.mocked(revealDocumentNumber).mockRejectedValue(new Error("Number unavailable"));
    mount(); const user = userEvent.setup();
    await user.click((await screen.findAllByRole("button", { name: "Show number" }))[0]);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hide number" })).not.toBeInTheDocument();
    expect(screen.queryByText("06ABCDE1234F1Z1")).not.toBeInTheDocument();
  });
});
