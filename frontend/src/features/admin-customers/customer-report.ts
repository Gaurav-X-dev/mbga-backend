import type { Customer } from "../../api/customers.api";
import { customerName } from "./customer-utils";

export function registrationDay(value?: string | null): string {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Not recorded";
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit"
  }).formatToParts(date);
  const part = (type: string) => parts.find((p) => p.type === type)?.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export function customerReport(customers: Customer[], option: string) {
  if (option === "employees" || option === "daily") {
    const groups = new Map<string, { label: string; count: number }>();
    for (const customer of customers) {
      const key = option === "daily" ? registrationDay(customer.registeredAt) : customer.employeeId || "Not recorded";
      const group = groups.get(key) ?? {
        label: option === "daily" ? key : customer.employeeName || customer.employeeId || "Not recorded", count: 0
      };
      group.count++;
      groups.set(key, group);
    }
    return {
      header: option === "daily" ? ["Registration date (IST)", "Customers acquired"] : ["Employee ID", "Employee", "Customers acquired"],
      rows: [...groups.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([key, group]) =>
        option === "daily" ? [key, group.count] : [key, group.label, group.count])
    };
  }
  return {
    header: ["Customer code", "Customer", "Mobile", "Type", "Account status", "KYC status", "Employee ID", "Employee", "Registration date (IST)"],
    rows: customers.map((c) => [c.code, customerName(c), c.mobile, c.customerType, c.accountStatus, c.kycStatus,
      c.employeeId, c.employeeName || "Not recorded", registrationDay(c.registeredAt)])
  };
}
