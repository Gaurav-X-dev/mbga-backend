import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "./client";
import { tokenStorage } from "../auth/token-storage";
import * as customers from "./customers.api";
import { listOrders } from "./orders.api";

vi.mock("./client", () => ({ apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
vi.mock("../auth/token-storage", () => ({ tokenStorage: { get: vi.fn() } }));
beforeEach(() => {
  vi.clearAllMocks();
  for (const method of [apiClient.get, apiClient.post, apiClient.patch, apiClient.put, apiClient.delete]) vi.mocked(method).mockResolvedValue({ data: {} });
});
describe.each(["admin", "merchant"] as const)("%s customer API routing", channel => {
  beforeEach(() => vi.mocked(tokenStorage.get).mockReturnValue({ channel, accessToken: "test", refreshToken: "test" }));
  it("routes all customer operations to the signed-in channel", async () => {
    const body = {} as customers.CustomerCreateInput;
    await customers.createCustomer("m1", body);
    await customers.getCustomer("m1", "c1");
    await customers.getCustomerEligibility("m1", "c1");
    await customers.getCustomerPricing("m1", "c1");
    await customers.getCustomerPaymentSummary("m1", "c1");
    await customers.approveCustomer("m1", "c1");
    await customers.rejectCustomer("m1", "c1", "Correction required");
    await customers.getDocumentUrl("m1", "f1");
    await customers.createCustomerBranch("m1", "owner", body);
    const calls = [...vi.mocked(apiClient.get).mock.calls, ...vi.mocked(apiClient.post).mock.calls];
    expect(calls).toHaveLength(9);
    for (const [url] of calls) expect(url).toMatch(new RegExp(`^/${channel}/`));
    expect(apiClient.post).toHaveBeenCalledWith(`/${channel}/customer-access/customers/owner/branches`, body, channel === "admin" ? { params: { merchantId: "m1" } } : {});
  });
  it("routes customer order history to its channel", async () => {
    await listOrders({merchantId:"m1",customerId:"c1"});
    expect(apiClient.get).toHaveBeenCalledWith(`/${channel}/orders`, expect.objectContaining({params: expect.objectContaining({customerId:"c1"})}));
  });
});
