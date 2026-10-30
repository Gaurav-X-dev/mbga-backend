import type { LocationLog } from "../../api/live-location.api";
import { mapsUrl } from "./tracking-utils";
export type Stop = { points: LocationLog[]; seconds: number | null };
export function distance(a: LocationLog, b: LocationLog) {
  const rad = Math.PI / 180;
  const h = Math.sin((b.latitude-a.latitude)*rad/2)**2 + Math.cos(a.latitude*rad)*Math.cos(b.latitude*rad)*Math.sin((b.longitude-a.longitude)*rad/2)**2;
  return 12742000*Math.asin(Math.sqrt(Math.min(1,Math.max(0,h))));
}
export function analyseRoute(items: LocationLog[], radius = 30, gapSeconds = 300) {
  const ordered = [...items].sort((a,b) => Date.parse(a.recorded_at)-Date.parse(b.recorded_at) || a.id.localeCompare(b.id));
  const segments: LocationLog[][] = [], stops: Stop[] = [];
  const byId = new Map<string, Stop>();
  let previous: LocationLog | undefined, segment: LocationLog[] = [], cluster: LocationLog[] = [], skipped = 0;
  function finishStop() {
    if (!cluster.length) return;
    const seconds = (Date.parse(cluster[cluster.length-1].recorded_at)-Date.parse(cluster[0].recorded_at))/1000;
    const stop = { points: cluster, seconds: seconds > 0 ? seconds : null };
    stops.push(stop); cluster.forEach(point => byId.set(point.id, stop)); cluster = [];
  }
  for (const point of ordered) {
    if (point.is_future || !Number.isFinite(Date.parse(point.recorded_at)) || !mapsUrl(point.latitude,point.longitude)) {
      finishStop(); previous = undefined; segment = []; skipped++; continue;
    }
    const gap = previous ? (Date.parse(point.recorded_at)-Date.parse(previous.recorded_at))/1000 : 0;
    const broken = !previous || gap > gapSeconds || (gap === 0 && distance(previous,point) > 0.1);
    if (broken) { finishStop(); segment = []; segments.push(segment); }
    if (cluster.length && distance(cluster[0],point) > radius) finishStop();
    cluster.push(point); segment.push(point); previous = point;
  }
  finishStop();
  return { segments, stops, byId, skipped, points: segments.flat() };
}
