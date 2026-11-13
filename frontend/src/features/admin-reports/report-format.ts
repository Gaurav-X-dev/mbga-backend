import { formatCurrency, formatNumber, humanize } from "../../utils/format";

/*
 * Reports carry no unit per figure, so the label or column key decides. Counts win over money:
 * "Tax invoices" is a number of invoices, not an amount of tax, while "Invoice amount" and
 * "GST collected" are money.
 */
const MONEY = /amount|total|revenue|price|value|balance|expense|cost|gst|tax|profit|loss|collected|subtotal|paid|due|cash|upi|neft|outstanding|spend/i;
const COUNT =
  /count|qty|quantity|cylinders|deliveries|orders|entries|empties|invoices|payments|receipts|bills|slips|records|transactions|customers|merchants|sites|vehicles|drivers|helpers|movements|days|items|number of|no\. of|\bnos?\b|#/i;
/** Ratios ("Collection rate", "GST %") would otherwise read as money. */
const PERCENT = /percent|%|rate|ratio|share/i;

export function isMoneyFigure(label: string) {
  return MONEY.test(label) && !COUNT.test(label) && !PERCENT.test(label);
}

export function formatReportFigure(label: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value !== "number") return String(value);
  if (PERCENT.test(label)) return `${formatNumber(value)}%`;
  return isMoneyFigure(label) ? formatCurrency(value) : formatNumber(value);
}

/** Cylinder codes arrive raw ("LPG_47_5KG_L"); make them readable without a lookup table. */
export function cylinderLabel(code: string) {
  const match = /^LPG_(\d+)(?:_(\d+))?KG(?:_(.+))?$/i.exec(code);
  if (!match) return humanize(code);
  const [, whole, fraction, suffix] = match;
  const weight = fraction ? `${whole}.${fraction}` : whole;
  const tag = suffix ? ` ${suffix === "L" ? "(LOT)" : suffix === "V" ? "(VOT)" : humanize(suffix)}` : "";
  return `${weight} kg${tag}`;
}

