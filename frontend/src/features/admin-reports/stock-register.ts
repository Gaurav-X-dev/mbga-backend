import { cylinderLabel } from "./report-format";

/*
 * The godown stock register, rebuilt from the stock-movement report.
 *
 * The report gives movements (date, type, cylinder, filled/empty deltas) but no opening stock.
 * The live inventory gives today's counts. Walking backwards from today, subtracting every
 * movement since, gives the stock at any earlier moment - so each day's opening and closing
 * come out exact, as long as the movements cover everything from that day up to now.
 */

export type Movement = {
  id: string;
  date: string;
  type: string;
  cylinderType: string;
  quantity: number;
  filled: number;
  empty: number;
  reference?: string | null;
  notes?: string | null;
};

export type FE = { f: number; e: number };
export type Counts = Record<string, FE>;

/** The register's lines, in the order a godown keeper writes them. */
/** Like the paper book: morning stock is opening plus what arrived; everything that leaves comes after. */
export const LINES = [
  { key: "received", label: "+ Received from plant", block: "morning" },
  { key: "delivered", label: "− Delivered to customers", block: "supply" },
  { key: "collected", label: "+ Empties collected", block: "supply" },
  { key: "toPlant", label: "− Sent to plant", block: "supply" },
  { key: "adjust", label: "± Damage / corrections", block: "supply" }
] as const;
export type LineKey = (typeof LINES)[number]["key"];

function lineFor(type: string): LineKey {
  switch (type) {
    case "RECEIVED_FILLED":
      return "received";
    case "SENT_TO_PLANT":
      return "toPlant";
    case "DISPATCHED":
      return "delivered";
    case "EMPTIES_COLLECTED":
      return "collected";
    default:
      return "adjust";
  }
}

export type RegisterDay = {
  day: string;
  opening: Counts;
  lines: Record<LineKey, Counts>;
  /** Opening plus the morning block - what the godown held before supply went out. */
  morning: Counts;
  closing: Counts;
  notes: string[];
  movementCount: number;
};

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : 0);

/** Report rows → movements. The deltas are on the row, or in `_details.fields` for older shapes. */
export function toMovements(rows: Array<Record<string, unknown>>): Movement[] {
  return rows
    .filter((r) => typeof r.date === "string" && typeof r.cylinderType === "string")
    .map((r) => {
      const fields = ((r._details as { fields?: Array<{ label: string; value: unknown }> } | undefined)?.fields ?? []).reduce<
        Record<string, unknown>
      >((acc, f) => ({ ...acc, [f.label.toLowerCase()]: f.value }), {});
      return {
        id: String(r.id),
        date: String(r.date),
        type: String(r.type ?? ""),
        cylinderType: String(r.cylinderType),
        quantity: num(r.quantity),
        filled: num(r.filledDelta ?? fields["filled delta"]),
        empty: num(r.emptyDelta ?? fields["empty delta"]),
        reference: (r.reference as string | null) ?? null,
        notes: ((r._details as { notes?: string | null } | undefined)?.notes as string | null) ?? null
      };
    });
}

/** Calendar day in IST, which is the day the register is kept in. */
export function istDay(iso: string) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(iso));
}

const empty = (types: string[]): Counts => Object.fromEntries(types.map((t) => [t, { f: 0, e: 0 }]));
const clone = (c: Counts): Counts => Object.fromEntries(Object.entries(c).map(([k, v]) => [k, { ...v }]));

/** Cylinder types smallest first, as the register's columns run. */
export function orderTypes(types: Iterable<string>) {
  const weight = (code: string) => Number.parseFloat(cylinderLabel(code)) || Number.MAX_SAFE_INTEGER;
  return [...new Set(types)].sort((a, b) => weight(a) - weight(b) || a.localeCompare(b));
}

/**
 * @param shown   movements in the report's period (the days to draw)
 * @param sinceStart every movement from the period start up to now (to walk back from `current`)
 * @param current live stock now; when absent, opening/closing are left out and only the lines show
 */
export function buildRegister(
  shown: Movement[],
  sinceStart: Movement[],
  current: Counts | null,
  types: string[],
  /** Fill quiet days up to this day (inclusive), so stock carries forward like a real register. */
  untilDay?: string
): RegisterDay[] {
  const byDay = new Map<string, Movement[]>();
  for (const m of shown) {
    const d = istDay(m.date);
    byDay.set(d, [...(byDay.get(d) ?? []), m]);
  }
  const moving = [...byDay.keys()].sort();
  if (moving.length && untilDay) {
    // Capped so an all-time range does not draw a year of empty cards.
    const MAX_DAYS = 62;
    const cursor = new Date(`${moving[0]}T12:00:00+05:30`);
    const last = new Date(`${untilDay}T12:00:00+05:30`);
    let guard = 0;
    while (cursor <= last && guard++ < MAX_DAYS * 6) {
      const d = istDay(cursor.toISOString());
      if (!byDay.has(d) && (last.getTime() - cursor.getTime()) / 86_400_000 < MAX_DAYS) byDay.set(d, []);
      cursor.setDate(cursor.getDate() + 1);
    }
  }
  const days = [...byDay.keys()].sort().reverse(); // newest first

  // Closing of day D = now − everything after D.
  const closingFor = (day: string): Counts | null => {
    if (!current) return null;
    const c = clone(current);
    for (const t of types) c[t] ??= { f: 0, e: 0 };
    for (const m of sinceStart) {
      if (istDay(m.date) <= day) continue;
      c[m.cylinderType] ??= { f: 0, e: 0 };
      c[m.cylinderType].f -= m.filled;
      c[m.cylinderType].e -= m.empty;
    }
    return c;
  };

  return days.map((day) => {
    const moves = byDay.get(day)!;
    const lines = Object.fromEntries(LINES.map((l) => [l.key, empty(types)])) as Record<LineKey, Counts>;
    for (const m of moves) {
      const bucket = lines[lineFor(m.type)];
      bucket[m.cylinderType] ??= { f: 0, e: 0 };
      bucket[m.cylinderType].f += m.filled;
      bucket[m.cylinderType].e += m.empty;
    }
    const closing = closingFor(day) ?? empty(types);
    const net = (keys: LineKey[]) => {
      const c = empty(types);
      for (const k of keys)
        for (const [t, v] of Object.entries(lines[k])) {
          c[t] ??= { f: 0, e: 0 };
          c[t].f += v.f;
          c[t].e += v.e;
        }
      return c;
    };
    const all = net(LINES.map((l) => l.key));
    const morningMoves = net(["received"]);
    const opening = Object.fromEntries(types.map((t) => [t, { f: (closing[t]?.f ?? 0) - all[t].f, e: (closing[t]?.e ?? 0) - all[t].e }]));
    const morning = Object.fromEntries(types.map((t) => [t, { f: opening[t].f + morningMoves[t].f, e: opening[t].e + morningMoves[t].e }]));

    return { day, opening, lines, morning, closing, notes: moves.length ? notesFor(moves) : ["No stock movement — carried forward."], movementCount: moves.length };
  });
}

/** The lines written under the register, e.g. "Received 288 × 19 kg filled from the plant". */
function notesFor(moves: Movement[]): string[] {
  const sum = (type: string) => {
    const by = new Map<string, number>();
    for (const m of moves.filter((x) => x.type === type)) by.set(m.cylinderType, (by.get(m.cylinderType) ?? 0) + m.quantity);
    return orderTypes(by.keys()).map((t) => `${by.get(t)} × ${cylinderLabel(t)}`);
  };
  const notes: string[] = [];
  const received = sum("RECEIVED_FILLED");
  if (received.length) notes.push(`Received from plant (filled): ${received.join(", ")}`);
  const sent = sum("SENT_TO_PLANT");
  if (sent.length) notes.push(`Sent to plant: ${sent.join(", ")}`);
  const delivered = sum("DISPATCHED");
  const slips = new Set(moves.filter((m) => m.type === "DISPATCHED" && m.reference).map((m) => m.reference));
  if (delivered.length) notes.push(`Delivered on ${slips.size} slip${slips.size === 1 ? "" : "s"}: ${delivered.join(", ")}`);
  const collected = sum("EMPTIES_COLLECTED");
  if (collected.length) notes.push(`Empties collected: ${collected.join(", ")}`);
  const damaged = sum("MARKED_DAMAGED");
  if (damaged.length) notes.push(`Marked damaged: ${damaged.join(", ")}`);
  const corrections = moves.filter((m) => m.type === "CORRECTION").length;
  if (corrections) notes.push(`${corrections} audit correction${corrections === 1 ? "" : "s"}`);
  return notes;
}
