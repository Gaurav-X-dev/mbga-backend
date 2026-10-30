import { describe, expect, it } from "vitest";
import type { Customer } from "../../api/customers.api";
import { customerReport, registrationDay } from "./customer-report";

const customer = (overrides: Partial<Customer>) => ({
  id: "c", mobile: "9876543210", businessName: "Store", accountStatus: "ACTIVE",
  kycStatus: "VERIFIED", runningBalance: 0, pricingTier: "STANDARD", deliveryAddress: {}, ...overrides
} as Customer);

describe("customer acquisition reports", () => {
  it("uses Indian calendar dates at midnight boundaries", () => {
    expect(registrationDay("2026-10-01T18:29:59Z")).toBe("2026-10-01");
    expect(registrationDay("2026-10-01T18:30:00Z")).toBe("2026-10-02");
    expect(registrationDay(null)).toBe("Not recorded");
  });
  it("keeps employees with the same name separate and retains unknown creators", () => {
    const report = customerReport([
      customer({employeeId: "a", employeeName: "Alex"}),
      customer({employeeId: "b", employeeName: "Alex"}),
      customer({employeeId: "a", employeeName: "Alex"}), customer({})
    ], "employees");
    expect(report.rows).toContainEqual(["a", "Alex", 2]);
    expect(report.rows).toContainEqual(["b", "Alex", 1]);
    expect(report.rows).toContainEqual(["Not recorded", "Not recorded", 1]);
  });
  it("groups acquisition by registration day and exports raw customer rows", () => {
    const rows = [customer({registeredAt: "2026-10-01T18:30:00Z"}), customer({registeredAt: "2026-10-02T00:00:00Z"})];
    expect(customerReport(rows, "daily").rows).toEqual([["2026-10-02", 2]]);
    expect(customerReport(rows, "customers").rows).toHaveLength(2);
    expect(customerReport([], "customers").rows).toEqual([]);
  });
});
