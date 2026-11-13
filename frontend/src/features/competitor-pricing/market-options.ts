export const cylinders = [
  { value: "LPG_5KG", label: "5 kg · Mini" }, { value: "LPG_10KG", label: "10 kg · Composite" },
  { value: "LPG_19KG", label: "19 kg · Domestic" }, { value: "LPG_47_5KG_L", label: "47.5 kg · LOT" },
  { value: "LPG_47_5KG_V", label: "47.5 kg · VOT" }, { value: "LPG_422KG_HIPPO", label: "422 kg · Hippo" }
];
export const customers = ["Retail (Domestic)", "Commercial (Industrial)"].map(value => ({ value, label: value }));
export function today() { return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date()); }
export function validPrice(value: string) { return /^\d+(\.\d{1,2})?$/.test(value) && Number(value) > 0 && Number(value) <= 99999999.99; }
