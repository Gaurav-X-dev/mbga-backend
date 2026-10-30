import type { Customer } from "../../api/customers.api";

/** The name a customer is shown by: business first, then owner, then the number they sign in with. */
export function customerName(customer: Pick<Customer, "businessName" | "ownerName" | "mobile">) {
  return customer.businessName || customer.ownerName || customer.mobile;
}
