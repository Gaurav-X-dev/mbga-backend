import { apiClient } from "./client";
import { cleanParams } from "./params";

/**
 * Admin channel: /admin/catalogue.
 *
 * The business catalogue is platform-wide, not merchant-scoped: a cylinder type is the same
 * cylinder on every agency's price card, so there is no `merchantId` on these calls and no
 * merchant picker on the screen.
 *
 * Nothing is ever deleted. `isActive: false` retires a row, because orders, invoices and stock
 * movements already name it and a receipt has to keep reading the way it was printed.
 * `isProtected` marks the rows the platform itself depends on; those cannot be retired at all.
 */

const base = "/admin/catalogue";

export type CatalogueListParams = { includeInactive?: boolean };

// --- Cylinder types ---------------------------------------------------------------------------

export type CylinderType = {
  code: string;
  label: string;
  shortLabel?: string | null;
  weightKg: number;
  variant?: string | null;
  hsnSac?: string | null;
  unit: string;
  defaultBaseRate: number;
  defaultMarkup: number;
  gstPercent: number;
  reorderThreshold: number;
  sortOrder: number;
  isActive: boolean;
  isProtected: boolean;
  /** `defaultBaseRate + defaultMarkup`, worked out by the backend so both agree. */
  defaultUnitPrice: number;
};

export type CylinderTypeInput = {
  code?: string;
  label?: string;
  shortLabel?: string | null;
  weightKg?: number;
  variant?: string | null;
  hsnSac?: string | null;
  unit?: string;
  defaultBaseRate?: number;
  defaultMarkup?: number;
  gstPercent?: number;
  reorderThreshold?: number;
  sortOrder?: number;
  isActive?: boolean;
};

export async function listCylinderTypes(params: CatalogueListParams = {}, signal?: AbortSignal) {
  const { data } = await apiClient.get<CylinderType[]>(`${base}/cylinder-types`, {
    params: cleanParams(params),
    signal
  });
  return data;
}

export async function createCylinderType(input: CylinderTypeInput) {
  const { data } = await apiClient.post<CylinderType>(`${base}/cylinder-types`, input);
  return data;
}

export async function updateCylinderType(code: string, input: CylinderTypeInput) {
  const { data } = await apiClient.patch<CylinderType>(`${base}/cylinder-types/${encodeURIComponent(code)}`, input);
  return data;
}

// --- Customer types ---------------------------------------------------------------------------

export type CustomerType = {
  code: string;
  label: string;
  description?: string | null;
  codePrefix: string;
  requiresDeliverySites: boolean;
  requiresGstInvoice: boolean;
  isDefault: boolean;
  sortOrder: number;
  isActive: boolean;
  isProtected: boolean;
};

export type CustomerTypeInput = {
  code?: string;
  label?: string;
  description?: string | null;
  codePrefix?: string;
  requiresDeliverySites?: boolean;
  requiresGstInvoice?: boolean;
  isDefault?: boolean;
  sortOrder?: number;
  isActive?: boolean;
};

export async function listCustomerTypes(params: CatalogueListParams = {}, signal?: AbortSignal) {
  const { data } = await apiClient.get<CustomerType[]>(`${base}/customer-types`, {
    params: cleanParams(params),
    signal
  });
  return data;
}

export async function createCustomerType(input: CustomerTypeInput) {
  const { data } = await apiClient.post<CustomerType>(`${base}/customer-types`, input);
  return data;
}

export async function updateCustomerType(code: string, input: CustomerTypeInput) {
  const { data } = await apiClient.patch<CustomerType>(`${base}/customer-types/${encodeURIComponent(code)}`, input);
  return data;
}

// --- KYC document types -----------------------------------------------------------------------

export type KycDocumentType = {
  code: string;
  label: string;
  numberPattern?: string | null;
  minLength?: number | null;
  maxLength?: number | null;
  expiryRequired: boolean;
  scanRequired: boolean;
  sortOrder: number;
  isActive: boolean;
  isProtected: boolean;
};

export type KycDocumentTypeInput = {
  code?: string;
  label?: string;
  numberPattern?: string | null;
  minLength?: number | null;
  maxLength?: number | null;
  expiryRequired?: boolean;
  scanRequired?: boolean;
  sortOrder?: number;
  isActive?: boolean;
};

export async function listKycDocumentTypes(params: CatalogueListParams = {}, signal?: AbortSignal) {
  const { data } = await apiClient.get<KycDocumentType[]>(`${base}/kyc-document-types`, {
    params: cleanParams(params),
    signal
  });
  return data;
}

export async function createKycDocumentType(input: KycDocumentTypeInput) {
  const { data } = await apiClient.post<KycDocumentType>(`${base}/kyc-document-types`, input);
  return data;
}

export async function updateKycDocumentType(code: string, input: KycDocumentTypeInput) {
  const { data } = await apiClient.patch<KycDocumentType>(
    `${base}/kyc-document-types/${encodeURIComponent(code)}`,
    input
  );
  return data;
}

// --- What each customer type may order, and which documents it must produce --------------------

export type CylinderEligibility = {
  cylinderTypeCode: string;
  minQuantity: number;
  maxQuantity?: number | null;
  sortOrder: number;
  isActive: boolean;
};

export type KycRule = {
  documentTypeCode: string;
  requirementMode: "REQUIRED" | "OPTIONAL" | "ANY_OF";
  requirementGroup?: string | null;
  minRequired: number;
  isActive: boolean;
  sortOrder: number;
};

export async function getCylinderEligibility(code: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<CylinderEligibility[]>(
    `${base}/customer-types/${encodeURIComponent(code)}/cylinders`,
    { signal }
  );
  return data;
}

/** Replaces the whole list, so always send every row that should remain. */
export async function setCylinderEligibility(code: string, items: CylinderEligibility[]) {
  const { data } = await apiClient.put<CylinderEligibility[]>(
    `${base}/customer-types/${encodeURIComponent(code)}/cylinders`,
    { items }
  );
  return data;
}

export async function getKycRules(code: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<KycRule[]>(`${base}/customer-types/${encodeURIComponent(code)}/kyc-rules`, {
    signal
  });
  return data;
}

/** Replaces the whole list, so always send every rule that should remain. */
export async function setKycRules(code: string, items: KycRule[]) {
  const { data } = await apiClient.put<KycRule[]>(`${base}/customer-types/${encodeURIComponent(code)}/kyc-rules`, {
    items
  });
  return data;
}
