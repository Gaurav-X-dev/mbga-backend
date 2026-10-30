export type CylinderType = {
  code: string;
  label: string;
  shortLabel: string;
  weightKg: number;
  description: string;
  industrialOnly: boolean;
  minQuantity: number;
  maxQuantity: number;
};

export const CYLINDER_TYPES: CylinderType[] = [
  { code: "LPG_5KG", label: "5 KG", shortLabel: "5 KG", weightKg: 5, description: "Small commercial / FTL", industrialOnly: false, minQuantity: 1, maxQuantity: 100 },
  { code: "LPG_10KG", label: "10 KG", shortLabel: "10 KG", weightKg: 10, description: "Composite / Medium commercial", industrialOnly: false, minQuantity: 1, maxQuantity: 100 },
  { code: "LPG_19KG", label: "19 KG", shortLabel: "19 KG", weightKg: 19, description: "Standard commercial", industrialOnly: false, minQuantity: 1, maxQuantity: 50 },
  { code: "LPG_47_5KG_L", label: "47.5 KG L", shortLabel: "47.5 L", weightKg: 47.5, description: "Liquid off-take", industrialOnly: true, minQuantity: 1, maxQuantity: 30 },
  { code: "LPG_47_5KG_V", label: "47.5 KG V", shortLabel: "47.5 V", weightKg: 47.5, description: "Vapour off-take", industrialOnly: true, minQuantity: 1, maxQuantity: 30 },
  { code: "LPG_422KG_HIPPO", label: "422 KG Hippo", shortLabel: "422 KG", weightKg: 422, description: "Industrial only", industrialOnly: true, minQuantity: 1, maxQuantity: 5 },
];

export function cylinderLabel(code: string): string {
  return CYLINDER_TYPES.find((c) => c.code === code)?.label ?? code;
}

export function cylinderShortLabel(code: string): string {
  return CYLINDER_TYPES.find((c) => c.code === code)?.shortLabel ?? code;
}

export function cylinderTypesFor(customerType: string | null | undefined): CylinderType[] {
  if (customerType === "INDUSTRIAL") {
    return CYLINDER_TYPES.filter((c) => c.code !== "LPG_5KG" && c.code !== "LPG_10KG");
  }
  return CYLINDER_TYPES.filter((c) => !c.industrialOnly);
}
