import { describe, expect, it } from "vitest";
import type { LocationLog } from "../../api/live-location.api";
import { analyseRoute } from "./route-analysis";
const point = (id: string, seconds: number, metres = 0): LocationLog => ({ id, latitude:28+metres/111195, longitude:77, recorded_at:new Date(Date.UTC(2026,9,29,10,0,seconds)).toISOString(), received_at:"2026-10-29T10:00:00Z", accuracy:5, is_future:false });
describe("observed GPS route", () => {
  it("sorts pings and calculates stay only between observations within tolerance", () => {
    const data = analyseRoute([point("b",120,10),point("a",0),point("c",240,15)]);
    expect(data.points.map(p=>p.id)).toEqual(["a","b","c"]);
    expect(data.byId.get("b")?.seconds).toBe(240);
  });
  it("breaks long gaps and separates return visits", () => {
    const data = analyseRoute([point("a",0),point("b",60),point("c",120,100),point("d",180),point("e",600)]);
    expect(data.segments).toHaveLength(2);
    expect(data.byId.get("a")?.seconds).toBe(60);
    expect(data.byId.get("d")?.seconds).toBeNull();
    expect(data.byId.get("e")?.seconds).toBeNull();
  });
  it("does not infer duration or travel from duplicate conflicting timestamps", () => {
    const data = analyseRoute([point("a",0),point("b",0,100)]);
    expect(data.segments).toHaveLength(2);
    expect(data.stops.every(stop=>stop.seconds===null)).toBe(true);
  });
  it("excludes invalid/future observations and breaks connections across them", () => {
    const data = analyseRoute([point("a",0),{...point("b",60),is_future:true},point("c",120),{...point("d",180),latitude:91}]);
    expect(data.skipped).toBe(2);
    expect(data.segments).toHaveLength(2);
    expect(data.stops.every(stop=>stop.seconds===null)).toBe(true);
  });
});
