import { describe, expect, it } from "vitest";

import { cylinderLabel, formatReportFigure, isMoneyFigure } from "./report-format";

describe("report figures", () => {
  it.each(["Tax invoices", "Payments", "Cylinders delivered", "Orders", "Pending empties", "Number of customers"])(
    "%s is a count, not money",
    (label) => expect(isMoneyFigure(label)).toBe(false)
  );

  it.each(["Invoice amount", "GST collected", "Taxable value", "Total payable", "Tax amount", "Outstanding balance"])(
    "%s is money",
    (label) => expect(isMoneyFigure(label)).toBe(true)
  );

  it("formats counts, money and percentages", () => {
    expect(formatReportFigure("Tax invoices", 12)).toBe("12");
    expect(formatReportFigure("GST collected", 5949)).toContain("₹");
    expect(formatReportFigure("GST %", 18)).toBe("18%");
    expect(formatReportFigure("Status", "PAID")).toBe("PAID");
    expect(formatReportFigure("Anything", null)).toBe("—");
  });
});

describe("cylinder labels", () => {
  it.each([
    ["LPG_19KG", "19 kg"],
    ["LPG_47_5KG_L", "47.5 kg (LOT)"],
    ["LPG_47_5KG_V", "47.5 kg (VOT)"],
    ["LPG_422KG_HIPPO", "422 kg Hippo"]
  ])("%s reads as %s", (code, label) => expect(cylinderLabel(code)).toBe(label));
});
