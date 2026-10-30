import type { CustomerType, KycDocumentType } from "../../api/customers.api";
import type { Address } from "../../api/orders.api";
export { formatCurrency } from "../../utils/format";

export interface DocMeta {
  title: string;
  subtitle: string;
  icon: "idCard" | "fileText" | "shield" | "store";
  color: string;
  bgColor: string;
  badgeBg: string;
}

export const DOC_META: Record<KycDocumentType, DocMeta> = {
  AADHAAR: {
    title: "Aadhaar Card",
    subtitle: "Govt. issued identity proof",
    icon: "idCard",
    color: "#EA580C",
    bgColor: "rgba(234, 88, 12, 0.12)",
    badgeBg: "rgba(234, 88, 12, 0.15)"
  },
  PAN: {
    title: "PAN Card",
    subtitle: "Permanent Account Number",
    icon: "idCard",
    color: "#7C3AED",
    bgColor: "rgba(124, 58, 237, 0.12)",
    badgeBg: "rgba(124, 58, 237, 0.15)"
  },
  GST: {
    title: "GST Certificate",
    subtitle: "Goods & Services Tax",
    icon: "fileText",
    color: "#16A34A",
    bgColor: "rgba(22, 163, 74, 0.12)",
    badgeBg: "rgba(22, 163, 74, 0.15)"
  },
  FSSAI: {
    title: "FSSAI Licence",
    subtitle: "Food Safety and Standards",
    icon: "shield",
    color: "#D97706",
    bgColor: "rgba(217, 119, 6, 0.12)",
    badgeBg: "rgba(217, 119, 6, 0.15)"
  },
  MSME: {
    title: "MSME Certificate",
    subtitle: "Udyam Registration",
    icon: "store",
    color: "#2563EB",
    bgColor: "rgba(37, 99, 235, 0.12)",
    badgeBg: "rgba(37, 99, 235, 0.15)"
  }
};

export const ALL_DOC_TYPES: KycDocumentType[] = ["AADHAAR", "PAN", "GST", "FSSAI", "MSME"];

export const REQUIRED_DOCUMENTS: Record<CustomerType, KycDocumentType[]> = {
  RETAIL: ["AADHAAR"],
  INDUSTRIAL: ["FSSAI", "GST"]
};

export const MIN_REQUIRED_DOCS: Record<CustomerType, number> = {
  RETAIL: 1,
  INDUSTRIAL: 2
};

export const DOC_PATTERNS: Record<KycDocumentType, { regex: RegExp; hint: string; placeholder: string; maxLength: number }> = {
  AADHAAR: {
    regex: /^\d{12}$/,
    hint: "Aadhaar must be 12 digits (e.g. 123456789012)",
    placeholder: "e.g. 123456789012",
    maxLength: 12
  },
  PAN: {
    regex: /^[A-Z]{5}\d{4}[A-Z]$/,
    hint: "PAN must be 10 characters (e.g. ABCDE1234F)",
    placeholder: "e.g. ABCDE1234F",
    maxLength: 10
  },
  GST: {
    regex: /^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/,
    hint: "GSTIN must be 15 characters (e.g. 23AAACA1234F1Z5)",
    placeholder: "e.g. 23AAACA1234F1Z5",
    maxLength: 15
  },
  FSSAI: {
    regex: /^\d{14}$/,
    hint: "FSSAI licence must be 14 digits",
    placeholder: "e.g. 12345678901234",
    maxLength: 14
  },
  MSME: {
    regex: /^UDYAM-[A-Z]{2}-\d{2}-\d{7}$/,
    hint: "Format: UDYAM-XX-00-0000000 (e.g. UDYAM-MP-01-1234567)",
    placeholder: "e.g. UDYAM-DL-01-1234567",
    maxLength: 19
  }
};

export function formatDocumentInput(type: KycDocumentType, raw: string): string {
  const clean = raw.trim().toUpperCase();
  switch (type) {
    case "AADHAAR":
      return raw.replace(/\D/g, "").slice(0, 12);
    case "FSSAI":
      return raw.replace(/\D/g, "").slice(0, 14);
    case "PAN":
      return clean.replace(/[^A-Z0-9]/g, "").slice(0, 10);
    case "GST":
      return clean.replace(/[^A-Z0-9]/g, "").slice(0, 15);
    case "MSME":
      return clean.replace(/[^A-Z0-9\-]/g, "").slice(0, 19);
    default:
      return clean.slice(0, 30);
  }
}

export function validateDocumentNumber(type: KycDocumentType, value: string): string | undefined {
  const meta = DOC_META[type];
  if (!value || !value.trim()) return `${meta.title} number is required`;
  const pattern = DOC_PATTERNS[type];
  if (pattern && !pattern.regex.test(value.trim().toUpperCase())) {
    return pattern.hint;
  }
  return undefined;
}

export function isDocumentNumberValid(type: KycDocumentType, value: string): boolean {
  if (!value || !value.trim()) return false;
  const pattern = DOC_PATTERNS[type];
  return pattern ? pattern.regex.test(value.trim().toUpperCase()) : false;
}

export function maskIdentifier(value: string, visible = 4): string {
  const clean = value.replace(/\s/g, "");
  if (clean.length <= visible) return clean;
  return `${"•".repeat(clean.length - visible)}${clean.slice(-visible)}`;
}

export function formatFileSize(bytes?: number): string {
  if (!bytes) return "PDF / Image";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatMobile(mobile: string): string {
  const d = mobile.replace(/\D/g, "");
  if (d.length !== 10) return mobile;
  return `+91 ${d.slice(0, 5)} ${d.slice(5)}`;
}

export function validateBusinessName(value: string): string | undefined {
  const trimmed = value.trim();
  if (!trimmed) return "Business / shop name is required";
  if (trimmed.length < 2) return "Business name must be at least 2 characters";
  if (trimmed.length > 100) return "Business name cannot exceed 100 characters";
  return undefined;
}

export function validateName(value: string, label = "Contact person name"): string | undefined {
  const trimmed = value.trim();
  if (!trimmed) return `${label} is required`;
  if (trimmed.length < 2) return `${label} must be at least 2 characters`;
  if (trimmed.length > 60) return `${label} cannot exceed 60 characters`;
  return undefined;
}

export function validateMobile(value: string): string | undefined {
  const digits = value.replace(/\D/g, "");
  if (!digits) return "Customer mobile number is required";
  if (digits.length !== 10) return "Enter a valid 10-digit mobile number";
  if (!/^[6-9]/.test(digits)) return "Mobile number must start with 6, 7, 8 or 9";
  return undefined;
}

export function validateEmail(value?: string): string | undefined {
  if (!value || !value.trim()) return undefined;
  const clean = value.trim().toLowerCase();
  if (clean.length > 100) return "Email address cannot exceed 100 characters";
  if (!/^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(clean)) {
    return "Enter a valid email address (e.g. name@business.com)";
  }
  return undefined;
}

export function validateAddress(address: Partial<Address>): Record<string, string | undefined> {
  const errors: Record<string, string | undefined> = {};
  if (!address.pincode || !/^\d{6}$/.test(address.pincode.trim())) {
    errors.pincode = "Valid 6-digit pincode is required";
  }
  if (!address.line1 || !address.line1.trim()) {
    errors.line1 = "House, building or street address is required";
  }
  if (!address.city || !address.city.trim()) {
    errors.city = "City is required";
  }
  if (!address.state || !address.state.trim()) {
    errors.state = "State is required";
  }
  return errors;
}
