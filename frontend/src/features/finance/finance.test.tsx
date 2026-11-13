import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { listCustomers } from "../../api/customers.api";
import { beforeEach, expect, it, vi } from "vitest";
import { CashHandovers } from "./CashHandovers";
import { Advances } from "./Advances";
import * as finance from "../../api/finance.api";

vi.mock("../../auth/auth-context", () => ({ useAuth: () => ({ can: () => true }) }));
vi.mock("../../api/customers.api", () => ({ listCustomers: vi.fn().mockResolvedValue({ items: [{ id: "c1", businessName: "Shop One" }], total: 1 }) }));
vi.mock("../../api/finance.api", () => ({ getCash: vi.fn(), getHandovers: vi.fn(), submitHandover: vi.fn(), verifyHandover: vi.fn(), getAdvance: vi.fn(), getDeposits: vi.fn(), getLedger: vi.fn(), createDeposit: vi.fn(), verifyDeposit: vi.fn(), recordRefund: vi.fn() }));
const scope = { merchant: false, merchantId: "m1" };
function mount(content: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><MemoryRouter>{content}</MemoryRouter></QueryClientProvider>);
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(finance.getCash).mockResolvedValue({ items: [], total: 0, cashInCustody: 0, coverage: "New cash collections only", drivers: [{ id: "d1", name: "Driver One" }] });
  vi.mocked(finance.getHandovers).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(finance.getDeposits).mockResolvedValue({ items: [{ id: "deposit1", customerId: "c1", amount: 500, mode: "UPI", reference: "UTR1", status: "PENDING", notes: null, createdAt: "2026-11-03T10:00:00Z" }], total: 1 });
});
it("uses dynamic driver choices and does not submit an empty selection", async () => {
  const user = userEvent.setup(); mount(<CashHandovers scope={scope} />);
  expect(await screen.findByRole("option", { name: "Driver One" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Submit cash handover" })).toBeDisabled();
  await user.selectOptions(screen.getByLabelText("Driver"), "d1");
  await waitFor(() => expect(finance.getCash).toHaveBeenLastCalledWith(scope, expect.objectContaining({ driverId: "d1" }), expect.any(AbortSignal)));
  expect(finance.submitHandover).not.toHaveBeenCalled();
});
it("requires office confirmation before crediting a pending advance", async () => {
  const user = userEvent.setup(); mount(<Advances scope={scope} />);
  expect(screen.getByRole("button", { name: "Record advance deposit" })).toBeDisabled();
  expect(screen.getByText(/Select a customer above/)).toBeInTheDocument();
  await user.click((await screen.findAllByRole("button", { name: "Verify receipt" }))[0]);
  expect(finance.verifyDeposit).not.toHaveBeenCalled();
  await user.type(screen.getByLabelText("Verification / refund reason"), "Verified bank receipt");
  await user.click(screen.getByRole("button", { name: "Confirm received & credit advance" }));
  await waitFor(() => expect(finance.verifyDeposit).toHaveBeenCalledWith(scope, "deposit1", true, "Verified bank receipt"));
});

it("searches approved customers on the server and explains disabled merchant advances", async () => {
  vi.mocked(finance.getAdvance).mockResolvedValue({ customerId: "c1", balance: 0, reserved: 0, available: 0, enabled: false, autoUseAdvance: true, maxDepositAmount: 1000, allocationPolicy: "FUTURE_ORDERS_ONLY" });
  vi.mocked(finance.getLedger).mockResolvedValue({ items: [], total: 0 });
  const user = userEvent.setup(); mount(<Advances scope={scope} />);
  await user.click(screen.getByRole("button", { name: "Choose customer" }));
  await user.type(screen.getByLabelText("Search customers"), "Shop");
  await waitFor(() => expect(listCustomers).toHaveBeenLastCalledWith(expect.objectContaining({ search: "Shop", limit: 10, accountStatus: "APPROVED", merchantId: "m1" }), expect.any(AbortSignal)));
  await user.click(await screen.findByRole("button", { name: /Shop One/ }));
  expect(await screen.findByText(/Advance deposits are disabled for this merchant/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Record advance deposit" })).toBeDisabled();
  expect(screen.queryByLabelText("Search customers")).not.toBeInTheDocument();
});
it("allows a valid deposit only after selecting a customer with advances enabled", async () => {
  vi.mocked(finance.getAdvance).mockResolvedValue({ customerId: "c1", balance: 0, reserved: 0, available: 0, enabled: true, autoUseAdvance: true, maxDepositAmount: 1000, allocationPolicy: "FUTURE_ORDERS_ONLY" });
  vi.mocked(finance.getLedger).mockResolvedValue({ items: [], total: 0 });
  const user = userEvent.setup(); mount(<Advances scope={scope} />);
  await user.click(screen.getByRole("button", { name: "Choose customer" }));
  await user.click(await screen.findByRole("button", { name: /Shop One/ }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Record advance deposit" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "Record advance deposit" }));
  const submit = screen.getByRole("button", { name: "Submit for verification" });
  expect(submit).toBeDisabled();
  await user.type(screen.getByLabelText("Amount (₹)"), "1001");
  await user.type(screen.getByLabelText("Transaction / refund reference"), "UTR123");
  expect(submit).toBeDisabled();
  await user.clear(screen.getByLabelText("Amount (₹)")); await user.type(screen.getByLabelText("Amount (₹)"), "500");
  expect(submit).toBeEnabled();
  await user.click(submit);
  await waitFor(() => expect(finance.createDeposit).toHaveBeenCalledWith(scope, expect.objectContaining({ customerId: "c1", amount: 500, reference: "UTR123" })));
});
it("labels submitted receipts and gives office staff a direct verification action", async () => {
  vi.mocked(finance.getCash).mockResolvedValue({ items: [{ id: "p1", driverId: "d1", driverName: "Driver One", vehicle: "HR1", invoice: "INV1", cashAmount: 240, receivedAmount: 0, remaining: 240, submittedAmount: 240, collectedAt: "2026-11-03T10:00:00Z" }], total: 1, cashInCustody: 240, coverage: "New collections", drivers: [] });
  vi.mocked(finance.getHandovers).mockResolvedValue({ items: [{ id: "batch1", driverId: "d1", expectedAmount: 240, receivedAmount: null, difference: null, status: "SUBMITTED", notes: null, verificationNotes: null, createdAt: "2026-11-03T10:00:00Z", items: [{ invoice: "INV1", vehicle: "HR1", driverName: "Driver One", expectedAmount: 240, receivedAmount: 0 }] }], total: 1 });
  const user = userEvent.setup(); mount(<CashHandovers scope={scope} />);
  await user.click((await screen.findAllByRole("button", { name: "Verify cash" }))[0]);
  expect(screen.queryByRole("checkbox", { name: /Select INV1/ })).not.toBeInTheDocument();
  expect(screen.getByLabelText("Cash physically received (₹)")).toHaveValue(null);
  expect(finance.verifyHandover).not.toHaveBeenCalled();
});
it("explains why a driver cannot verify their own handover before allowing a submission", async () => {
  vi.mocked(finance.getHandovers).mockResolvedValue({ items: [{ id: "batch1", driverId: "d1", expectedAmount: 240, receivedAmount: null, difference: null, status: "SUBMITTED", notes: null, verificationNotes: null, createdAt: "2026-11-03T10:00:00Z", items: [], verificationBlockedReason: "Another authorized office user must verify this driver cash." }], total: 1 });
  const user = userEvent.setup(); mount(<CashHandovers scope={scope} />);
  await user.click((await screen.findAllByRole("button", { name: "View details" }))[0]);
  expect(screen.getByText("Another authorized office user must verify this driver cash.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Verify cash received" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Cash physically received (₹)")).not.toBeInTheDocument();
});
it("selects a cash receipt and preserves the same request key after a network retry", async () => {
  vi.mocked(finance.getCash).mockResolvedValue({ items: [{ id: "p1", driverId: "d1", driverName: "Driver One", vehicle: "HR1", invoice: "INV1", cashAmount: 500, receivedAmount: 0, remaining: 500, submittedAmount: 0, collectedAt: "2026-11-03T10:00:00Z" }], total: 1, cashInCustody: 500, coverage: "New collections", drivers: [] });
  vi.mocked(finance.submitHandover).mockRejectedValueOnce(new Error("Temporary network failure")).mockResolvedValueOnce({});
  const user = userEvent.setup(); mount(<CashHandovers scope={scope} />);
  await user.click((await screen.findAllByRole("checkbox", { name: "Select INV1 receipt p1" }))[0]);
  await user.click(screen.getByRole("button", { name: "Submit cash handover" }));
  await user.click(screen.getByRole("button", { name: "Confirm handover submission" }));
  await waitFor(() => expect(finance.submitHandover).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.getByRole("button", { name: "Confirm handover submission" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "Confirm handover submission" }));
  await waitFor(() => expect(finance.submitHandover).toHaveBeenCalledTimes(2));
  expect(vi.mocked(finance.submitHandover).mock.calls[0][1]).toEqual(vi.mocked(finance.submitHandover).mock.calls[1][1]);
  expect(vi.mocked(finance.submitHandover).mock.calls[0][1]).toMatchObject({ driverId: "d1", paymentIds: ["p1"] });
});
it("requires a counted whole-rupee amount and a reason before verifying cash", async () => {
  vi.mocked(finance.getHandovers).mockResolvedValue({ items: [{ id: "b1", driverId: "d1", expectedAmount: 500, receivedAmount: null, difference: null, status: "SUBMITTED", notes: null, verificationNotes: null, createdAt: "2026-11-03T10:00:00Z", items: [] }], total: 1 });
  const user = userEvent.setup(); mount(<CashHandovers scope={scope} />);
  await user.click((await screen.findAllByRole("button", { name: "Verify cash" }))[0]);
  const submit = screen.getByRole("button", { name: "Verify cash received" });
  expect(submit).toBeDisabled();
  await user.type(screen.getByLabelText("Cash physically received (₹)"), "400");
  expect(submit).toBeDisabled();
  await user.type(screen.getByLabelText("Count verification / difference explanation"), "Counted; short by 100");
  expect(submit).toBeEnabled();
  await user.click(submit);
  await waitFor(() => expect(finance.verifyHandover).toHaveBeenCalledWith(scope, "b1", 400, "Counted; short by 100", false));
});
