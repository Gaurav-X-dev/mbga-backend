import { describe, expect, it } from "vitest";

import { buildRegister, toMovements } from "./stock-register";

const row = (date: string, type: string, filledDelta: number, emptyDelta: number, quantity = Math.abs(filledDelta || emptyDelta)) => ({
  id: `${date}-${type}`,
  date,
  type,
  cylinderType: "LPG_19KG",
  quantity,
  filledDelta,
  emptyDelta,
  reference: type === "DISPATCHED" ? "DS-1" : null
});

describe("stock register", () => {
  // Day 1 (09 Oct): 200 filled arrive, 10 empties go to the plant.
  // Day 2 (10 Oct): 3 filled delivered, 5 empties collected. Live stock now: 300 F / 80 E.
  const rows = [
    row("2026-10-09T10:00:00+05:30", "RECEIVED_FILLED", 200, 0),
    row("2026-10-09T11:00:00+05:30", "SENT_TO_PLANT", 0, -10),
    row("2026-10-10T12:00:00+05:30", "DISPATCHED", -3, 0),
    row("2026-10-10T12:00:00+05:30", "EMPTIES_COLLECTED", 0, 5)
  ];
  const moves = toMovements(rows);
  const days = buildRegister(moves, moves, { LPG_19KG: { f: 300, e: 80 } }, ["LPG_19KG"]);

  it("lists days newest first", () => expect(days.map((d) => d.day)).toEqual(["2026-10-10", "2026-10-09"]));

  it("closes the latest day on the live count", () => expect(days[0].closing.LPG_19KG).toEqual({ f: 300, e: 80 }));

  it("works each opening back from the closing", () => {
    expect(days[0].opening.LPG_19KG).toEqual({ f: 303, e: 75 });
    expect(days[1].closing.LPG_19KG).toEqual({ f: 303, e: 75 });
    expect(days[1].opening.LPG_19KG).toEqual({ f: 103, e: 85 });
  });

  it("morning stock is opening plus receipts only; returns to the plant come after supply", () => {
    expect(days[1].morning.LPG_19KG).toEqual({ f: 303, e: 85 });
    expect(days[0].lines.delivered.LPG_19KG).toEqual({ f: -3, e: 0 });
    expect(days[0].lines.collected.LPG_19KG).toEqual({ f: 0, e: 5 });
  });

  it("writes register notes", () => {
    expect(days[1].notes).toContain("Received from plant (filled): 200 × 19 kg");
    expect(days[0].notes).toContain("Delivered on 1 slip: 3 × 19 kg");
  });
});

describe("register edge cases from real data", () => {
  it("never shows negative morning empties when empties go to the plant after collection (9 Oct)", () => {
    const moves = toMovements([
      row("2026-10-09T10:00:00+05:30", "EMPTIES_COLLECTED", 0, 146),
      row("2026-10-09T15:00:00+05:30", "SENT_TO_PLANT", 0, -25)
    ]);
    const [day] = buildRegister(moves, moves, { LPG_19KG: { f: 0, e: 135 } }, ["LPG_19KG"]);
    expect(day.opening.LPG_19KG.e).toBe(14);
    expect(day.morning.LPG_19KG.e).toBe(14);
    expect(day.closing.LPG_19KG.e).toBe(135);
  });

  it("carries stock forward through days with no movement", () => {
    const moves = toMovements([row("2026-10-10T10:00:00+05:30", "DISPATCHED", -1, 0)]);
    const days = buildRegister(moves, moves, { LPG_19KG: { f: 9, e: 0 } }, ["LPG_19KG"], "2026-10-12");
    expect(days.map((d) => d.day)).toEqual(["2026-10-12", "2026-10-11", "2026-10-10"]);
    expect(days[0].opening.LPG_19KG).toEqual({ f: 9, e: 0 });
    expect(days[1].closing.LPG_19KG).toEqual({ f: 9, e: 0 });
    expect(days[2].closing.LPG_19KG).toEqual({ f: 9, e: 0 });
    expect(days[2].opening.LPG_19KG).toEqual({ f: 10, e: 0 });
  });
});
