import { tokenStorage } from "../auth/token-storage";
import { apiClient } from "./client";
import { cleanParams } from "./params";

/** Admin channel: /admin/expenses. Merchant-scoped - `merchantId` on every call. */
export type ExpenseIcon = "fuel" | "maintenance" | "salary" | "rent" | "utilities" | "misc";

export type ExpenseCategory = {
  id: string;
  code: string;
  label: string;
  icon: ExpenseIcon | string;
  sortOrder: number;
  isActive: boolean;
  isCustom: boolean;
  expenseCount?: number;
};

export type ExpenseCategoryBrief = Pick<ExpenseCategory, "id" | "code" | "label" | "icon">;

export type FuelFields = {
  destination?: string | null;
  vehicleId?: string | null;
  vehicleNumber?: string | null;
  driverId?: string | null;
  driverName?: string | null;
  fuelType?: string | null;
  kmReading?: number | null;
  startOdometer?: number | null;
  endOdometer?: number | null;
  distance?: number | null;
  liters?: number | null;
  mileage?: number | null;
  hasReceipt?: boolean;
};
export type Expense = FuelFields & {
  id: string;
  category: ExpenseCategoryBrief;
  amount: number;
  note?: string | null;
  date: string;
  period: string;
  periodLabel: string;
  recordedBy: string;
  createdAt: string;
  updatedAt: string;
};

export type ExpenseSummary = {
  period?: string | null;
  periodLabel?: string | null;
  totalAmount: number;
  entryCount: number;
};

export type ExpenseListResponse = {
  items: Expense[];
  summary: ExpenseSummary;
  total: number;
  page: number;
  pageSize: number;
};

export type ExpensePeriod = {
  period: string;
  label: string;
  totalAmount: number;
  entryCount: number;
  isCurrent: boolean;
};

export type ExpenseCategoryTotal = {
  categoryId: string;
  code: string;
  label: string;
  icon: string;
  totalAmount: number;
  entryCount: number;
  sharePercent: number;
};

export type ExpenseBreakdown = ExpenseSummary & { categories?: ExpenseCategoryTotal[] };

export type ExpenseListParams = {
  merchantId: string;
  /** `YYYY-MM` or `ALL`. */
  period?: string;
  categoryId?: string;
  from?: string;
  to?: string;
  search?: string;
  page: number;
  pageSize: number;
};

export type ExpenseInput = FuelFields & {
  categoryId: string;
  amount: number;
  note?: string;
  /** Defaults to today on the server; may be back-dated, never post-dated. */
  date?: string;
};

export type CategoryInput = {
  label: string;
  icon?: string;
  sortOrder?: number;
  isActive?: boolean;
};

const base = () => `/${tokenStorage.get()?.channel === "merchant" ? "merchant" : "admin"}/expenses`;

const scoped = (merchantId: string) => ({ params: { merchantId } });

export async function listExpenses(params: ExpenseListParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<ExpenseListResponse>(base(), { params: cleanParams(params), signal });
  return data;
}

export async function listExpensePeriods(merchantId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<ExpensePeriod[]>(`${base()}/periods`, { ...scoped(merchantId), signal });
  return data;
}

export async function getExpenseBreakdown(merchantId: string, period: string, signal?: AbortSignal, range?: { from?: string; to?: string }) {
  const { data } = await apiClient.get<ExpenseBreakdown>(`${base()}/breakdown`, {
    params: cleanParams({ merchantId, period, ...range }),
    signal
  });
  return data;
}

export async function createExpense(merchantId: string, input: ExpenseInput) {
  const { data } = await apiClient.post<Expense>(base(), input, scoped(merchantId));
  return data;
}

/** Partial update; `note: ""` clears the note. */
export async function updateExpense(merchantId: string, expenseId: string, input: Partial<ExpenseInput>) {
  const { data } = await apiClient.patch<Expense>(`${base()}/${encodeURIComponent(expenseId)}`, input, scoped(merchantId));
  return data;
}

export async function deleteExpense(merchantId: string, expenseId: string) {
  await apiClient.delete(`${base()}/${encodeURIComponent(expenseId)}`, scoped(merchantId));
}

export async function listExpenseCategories(merchantId: string, includeInactive: boolean, signal?: AbortSignal) {
  const { data } = await apiClient.get<ExpenseCategory[]>(`${base()}/categories`, {
    params: { merchantId, includeInactive },
    signal
  });
  return data;
}

export async function createExpenseCategory(merchantId: string, input: CategoryInput) {
  const { data } = await apiClient.post<ExpenseCategory>(`${base()}/categories`, input, scoped(merchantId));
  return data;
}

export async function updateExpenseCategory(merchantId: string, categoryId: string, input: Partial<CategoryInput>) {
  const { data } = await apiClient.patch<ExpenseCategory>(
    `${base()}/categories/${encodeURIComponent(categoryId)}`,
    input,
    scoped(merchantId)
  );
  return data;
}

/** Deletes an unused category; one with expenses is deactivated instead (`isActive: false`). */
export async function deleteExpenseCategory(merchantId: string, categoryId: string) {
  const { data } = await apiClient.delete<ExpenseCategory>(
    `${base()}/categories/${encodeURIComponent(categoryId)}`,
    scoped(merchantId)
  );
  return data;
}

export async function getExpenseFuelOptions(merchantId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<{ vehicles: Array<{value: string; label: string}>; drivers: Array<{value: string; label: string}>; fuelTypes: Array<{value: string; label: string}> }>(`${base()}/fuel-options`, { ...scoped(merchantId), signal });
  return data;
}
export async function uploadExpenseReceipt(merchantId: string, expenseId: string, file: File) {
  const body = new FormData(); body.append("file", file);
  await apiClient.post(`${base()}/${encodeURIComponent(expenseId)}/receipt`, body, {...scoped(merchantId), timeout: 60_000});
}
export async function downloadExpenseReceipt(merchantId: string, expenseId: string) {
  const { data } = await apiClient.get<Blob>(`${base()}/${encodeURIComponent(expenseId)}/receipt`, {...scoped(merchantId), responseType: "blob"});
  const url = URL.createObjectURL(data);
  const link = document.createElement("a"); link.href = url;
  link.download = `expense-${expenseId}-receipt.${data.type.includes("pdf") ? "pdf" : data.type.includes("png") ? "png" : "jpg"}`;
  link.click(); URL.revokeObjectURL(url);
}
