import { useEffect, useMemo, useRef, useState } from "react";
import * as L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { LocationLog, TrackedDriver, TrackingRoute } from "../../api/live-location.api";
import { Button } from "../../components/common/Button";
import { analyseRoute } from "./route-analysis";
import { duration, locationTime, mapsUrl } from "./tracking-utils";

export default function DriverRouteMap({ route, fallback, focus }: { route?: TrackingRoute; fallback?: TrackedDriver; focus?: LocationLog }) {
  const host = useRef<HTMLDivElement>(null), map = useRef<L.Map | null>(null), bounds = useRef<L.LatLngBounds | null>(null);
  const fitted = useRef("");
  const [tileError,setTileError] = useState(false);
  const data = useMemo(() => analyseRoute(route?.items ?? [], route?.stationary_radius_metres, route?.max_ping_gap_seconds), [route]);
  const fallbackUrl = fallback && mapsUrl(fallback.current_latitude, fallback.current_longitude);
  const hasPoints = data.points.length > 0 || Boolean(fallbackUrl);
  useEffect(() => {
    if (!host.current || !hasPoints) return;
    const instance = L.map(host.current, { preferCanvas: true, scrollWheelZoom: false }); map.current = instance;
    const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a>',
      referrerPolicy: "strict-origin-when-cross-origin"
    }).addTo(instance);
    tiles.on("tileerror", () => setTileError(true));
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => instance.invalidateSize()) : null;
    observer?.observe(host.current);
    return () => { observer?.disconnect(); instance.remove(); map.current = null; fitted.current = ""; };
  }, [hasPoints]);
  useEffect(() => {
    const instance = map.current; if (!instance) return;
    const layer = L.featureGroup().addTo(instance);
    function label(point: LocationLog) {
      const stop = data.byId.get(point.id);
      const element = document.createElement("div"); element.style.whiteSpace = "pre-line";
      element.textContent = `${locationTime(point.recorded_at)}\n${point.latitude.toFixed(7)}, ${point.longitude.toFixed(7)}\nObserved stay: ${duration(stop?.seconds ?? null)}${stop && stop.seconds !== null ? `\n${locationTime(stop.points[0].recorded_at)} – ${locationTime(stop.points[stop.points.length-1].recorded_at)}\n${stop.points.length} GPS observations` : ""}`;
      return element;
    }
    data.segments.forEach(segment => { if (segment.length > 1) L.polyline(segment.map(p => [p.latitude,p.longitude]), {color: "#3159f5",weight: 4}).addTo(layer); });
    data.points.forEach((point,index) => {
      const color = index === 0 ? "#15803d" : index === data.points.length-1 ? "#dc2626" : "#3159f5";
      L.circleMarker([point.latitude,point.longitude], {radius: 4,color,fillOpacity: .8,weight: 1}).bindTooltip(() => label(point)).bindPopup(() => label(point)).addTo(layer);
    });
    data.stops.filter(stop => stop.seconds !== null).forEach(stop => {
      const point = stop.points[0];
      L.circleMarker([point.latitude,point.longitude],{radius:8,color:"#b45309",fillColor:"#fbbf24",fillOpacity:.8,weight:2}).bindTooltip(() => label(point)).bindPopup(() => label(point)).addTo(layer);
    });
    if (!data.points.length && fallback && fallbackUrl) {
      const node = document.createElement("div"); node.textContent = `Last known location · ${locationTime(fallback.last_location_at)}. Stay duration unavailable.`;
      L.circleMarker([fallback.current_latitude!,fallback.current_longitude!],{radius:8}).bindTooltip(node).bindPopup(node.cloneNode(true) as HTMLElement).addTo(layer);
    }
    if (focus && mapsUrl(focus.latitude,focus.longitude)) {
      L.circleMarker([focus.latitude,focus.longitude],{radius:10,color:"#7c3aed"}).bindPopup(() => label(focus)).addTo(layer).openPopup();
      instance.setView([focus.latitude,focus.longitude],17);
      host.current?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
    }
    bounds.current = layer.getBounds();
    const key = route ? `${route.from_date}:${route.to_date}` : "last-known";
    if (!focus && fitted.current !== key && bounds.current.isValid()) { instance.fitBounds(bounds.current,{padding:[28,28],maxZoom:17}); fitted.current = key; }
    return () => { layer.remove(); };
  }, [data,route,fallback,fallbackUrl,focus]);
  if (!hasPoints) return <p className="meta">No valid GPS observations available for this map.</p>;
  return <div className="stack">
    <div className="row"><Button size="sm" variant="secondary" onClick={() => { if (bounds.current?.isValid()) map.current?.fitBounds(bounds.current,{padding:[28,28],maxZoom:17}); }}>Fit route</Button>
      {fallbackUrl ? <a href={fallbackUrl} target="_blank" rel="noopener noreferrer">Open latest in Google Maps</a> : null}</div>
    {tileError ? <p role="status" className="meta">Map tiles are unavailable. GPS route and location logs remain available.</p> : null}
    <div ref={host} role="region" aria-label="Driver route on OpenStreetMap" style={{height:"clamp(320px, 50vh, 480px)",position:"relative",isolation:"isolate",borderRadius:12,overflow:"hidden"}} />
    <p className="meta">Green: first observation · Red: last observation · Amber: observed stop. Hover or tap a point for stay duration. Lines connect recorded GPS points; gaps over 5 minutes are disconnected. Stay uses a 30 m tolerance and ends at the last recorded ping.</p>
    {data.skipped ? <p className="meta">{data.skipped} invalid or future-dated observations excluded.</p> : null}
    <details><summary>Observed stops ({data.stops.filter(stop => stop.seconds !== null).length})</summary>
      <div style={{maxHeight:220,overflowY:"auto"}}>{data.stops.filter(stop => stop.seconds !== null).map(stop => <div key={stop.points[0].id}><Button variant="ghost" size="sm" onClick={() => map.current?.setView([stop.points[0].latitude,stop.points[0].longitude],18)}>{locationTime(stop.points[0].recorded_at)} · {duration(stop.seconds)}</Button></div>)}</div>
    </details>
  </div>;
}
