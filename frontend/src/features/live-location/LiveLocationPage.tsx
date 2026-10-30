import { lazy, Suspense, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listMerchants } from "../../api/merchants.api";
import { getLocationLogs, getTrackingRoute, listTracking, type LocationLog, type TrackedDriver } from "../../api/live-location.api";
import { normalizeError } from "../../api/errors";
import { queryKeys } from "../../api/query-keys";
import { Button } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { Badge, StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { Drawer, DrawerSection } from "../../components/feedback/Dialogs";
import { Alert, EmptyState, InlineError, LoadingSkeleton, RefreshIndicator } from "../../components/feedback/Feedback";
import { Field, Input, SearchInput, Select } from "../../components/forms/Field";
import { Card, DetailsPanel, PageHeader } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, TableHeader, type Column } from "../../components/tables/DataTable";
import { useSearchFilter, useUrlFilters } from "../../hooks/useUrlFilters";
import { formatMobileNumber } from "../../utils/mobile";
import { duration, locationTime, mapsUrl, todayIst } from "./tracking-utils";

const DriverRouteMap = lazy(() => import("./DriverRouteMap"));
const SIZE = 20;
const FILTERS = ["merchant", "status", "duty", "search"] as const;
const KEY = ["live-location"] as const;
const STATES = { RECENT: "Recent ping", STALE: "Stale location", FUTURE: "Device clock mismatch", UNKNOWN_TIME: "Update time unavailable", UNAVAILABLE: "Location unavailable" };

function MapLink({ latitude, longitude, name }: { latitude: number | null; longitude: number | null; name: string }) {
  const url = mapsUrl(latitude, longitude);
  return url ? <a className="icon-btn" href={url} target="_blank" rel="noopener noreferrer" title={`Open ${name} in Google Maps`} aria-label={`Open ${name} in Google Maps`}><Icon name="mapPin" size={18} /></a> : <span className="text-muted" title="No location available">—</span>;
}
function Coordinates({ latitude, longitude }: { latitude: number | null; longitude: number | null }) {
  return mapsUrl(latitude, longitude) ? <span className="mono text-small">{latitude!.toFixed(7)}, {longitude!.toFixed(7)}</span> : <span className="text-muted">Unavailable</span>;
}
function LocationState({ driver }: { driver: TrackedDriver }) {
  return <Badge tone={driver.location_state === "RECENT" && driver.can_view_logs ? "success" : driver.location_state === "UNAVAILABLE" ? "neutral" : "warning"}>
    {driver.location_state === "RECENT" && !driver.can_view_logs ? "Last known location" : STATES[driver.location_state] ?? "Unavailable"}
  </Badge>;
}
function ObservedDuration({ driver }: { driver: TrackedDriver }) {
  if (!driver.can_view_logs) return <span className="text-muted">Active / on-duty only</span>;
  return <span className="cell-stack"><strong>{driver.stationary_is_lower_bound ? "≥ " : ""}{duration(driver.stationary_seconds)}</strong>
    {driver.stationary_until ? <small title={`${locationTime(driver.stationary_since)} – ${locationTime(driver.stationary_until)}`}>Observed until last ping</small> : null}</span>;
}

function LocationHistory({ merchantId, driver, onClose }: { merchantId: string; driver: TrackedDriver; onClose: () => void }) {
  const [from, setFrom] = useState(todayIst);
  const [to, setTo] = useState(todayIst);
  const [page, setPage] = useState(1);
  const [focus, setFocus] = useState<LocationLog>();
  const days = (Date.parse(to) - Date.parse(from)) / 86400000;
  const validDates = Boolean(from && to && days >= 0 && days <= 30);
  const params = { merchantId, fromDate: from, toDate: to, limit: 50, offset: (page - 1) * 50 };
  const query = useQuery({ queryKey: [...KEY, "logs", merchantId, driver.id, params],
    queryFn: ({ signal }) => getLocationLogs(driver.id, params, signal),
    enabled: validDates && driver.can_view_logs,
    refetchInterval: query => ["DRIVER_TRACKING_UNAVAILABLE", "PERMISSION_DENIED"].includes(normalizeError(query.state.error).code ?? "") ? false : 15000,
    refetchIntervalInBackground: false, retry: false });
  const routeParams = { merchantId, fromDate: from, toDate: to };
  const route = useQuery({ queryKey: [...KEY, "route", driver.id, routeParams],
    queryFn: ({ signal }) => getTrackingRoute(driver.id, routeParams, signal),
    enabled: validDates && driver.can_view_logs && !query.error,
    refetchInterval: query => query.state.error ? false : 30000,
    refetchIntervalInBackground: false, retry: false });
  useEffect(() => { setFocus(undefined); }, [from, to]);
  const current = driver.can_view_logs ? query.data?.driver ?? driver : driver;
  const columns: Column<LocationLog>[] = [
    { key: "time", header: "Recorded (IST)", primary: true, render: item => <span className="cell-stack"><strong>{locationTime(item.recorded_at)}</strong>{item.is_future ? <Badge tone="warning">Device clock mismatch</Badge> : null}</span> },
    { key: "coordinates", header: "Coordinates", render: item => <Coordinates latitude={item.latitude} longitude={item.longitude} /> },
    { key: "accuracy", header: "Accuracy", render: item => item.accuracy === null ? "Not reported" : `±${item.accuracy} m` },
    { key: "received", header: "Received (IST)", render: item => locationTime(item.received_at) },
    { key: "map", header: "Map", render: item => <span className="row"><button className="icon-btn" aria-label="Show recorded position on route" onClick={() => setFocus({ ...item })}><Icon name="mapPin" size={18} /></button><MapLink latitude={item.latitude} longitude={item.longitude} name="recorded position" /></span> }
  ];
  return <Drawer open title={`${driver.full_name ?? "Driver"} · Location logs`} size="lg" onClose={onClose}>
    <DrawerSection title="Latest available location">
      <DetailsPanel items={[
        { label: "Driver code", value: driver.employee_code ?? "Not provided" },
        { label: "Duty", value: driver.on_duty ? "On Duty" : "Off Duty" },
        { label: "Coordinates", value: <Coordinates latitude={current.current_latitude} longitude={current.current_longitude} /> },
        { label: "Last update", value: locationTime(current.last_location_at) },
        { label: "Location", value: <LocationState driver={current} /> },
        { label: "Observed at same location", value: <ObservedDuration driver={current} /> }
      ]} />
    </DrawerSection>
    <DrawerSection title="Recorded location history">
      <div className="grid-2" style={{ marginBottom: 16 }}>
        <Field label="From date (IST)"><Input type="date" value={from} max={to || todayIst()} onChange={event => { setFrom(event.target.value); setPage(1); }} /></Field>
        <Field label="To date (IST)"><Input type="date" value={to} min={from} max={todayIst()} onChange={event => { setTo(event.target.value); setPage(1); }} /></Field>
      </div>
      {validDates && !query.error ? <div style={{ marginBottom: 24 }}>
        {driver.can_view_logs && route.isLoading ? <LoadingSkeleton rows={3} label="Loading route" /> : route.error ? <InlineError error={route.error} onRetry={() => void route.refetch()} /> :
          <Suspense fallback={<LoadingSkeleton rows={3} label="Loading map" />}><DriverRouteMap route={driver.can_view_logs ? route.data : undefined} fallback={!driver.can_view_logs ? current : undefined} focus={focus} /></Suspense>}
        {route.data?.truncated && !route.error ? <Alert tone="warning">Showing the most recent {route.data.limit.toLocaleString()} of {route.data.total.toLocaleString()} observations. Narrow the date range for the full route.</Alert> : null}
      </div> : null}
      {!driver.can_view_logs ? <Alert tone="info">Location history is available only while this driver is active, approved and on duty.</Alert> : !validDates ?
        <Alert tone="warning">Choose a valid date range of up to 31 days.</Alert> :
        <DataTable caption="Driver location history" columns={columns} rows={query.error ? undefined : query.data?.items} getRowKey={item => item.id}
          isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()}
          empty={<EmptyState icon="mapPin" title="No location logs" description="No GPS updates were recorded for the selected dates." />}
          footer={<Pagination page={page} pageSize={50} total={query.data?.total ?? 0} onPageChange={setPage} disabled={query.isFetching} itemLabel="location logs" />} />}
      <p className="meta">These are stored GPS observations, not a reconstructed route. History refreshes every 15 seconds while this panel is open.</p>
    </DrawerSection>
  </Drawer>;
}

export function LiveLocationPage() {
  const { values, page, setFilter, setPage } = useUrlFilters(FILTERS);
  const [search, setSearch] = useSearchFilter(values.search, value => setFilter("search", value));
  const [selected, setSelected] = useState<TrackedDriver | null>(null);
  const merchantId = values.merchant;
  const merchantParams = { limit: 100, offset: 0 };
  const merchants = useQuery({ queryKey: queryKeys.merchants.list(merchantParams), queryFn: ({ signal }) => listMerchants(merchantParams, signal), staleTime: 300000 });
  useEffect(() => { if (!merchantId && merchants.data?.items[0]) setFilter("merchant", merchants.data.items[0].id); }, [merchantId, merchants.data, setFilter]);
  useEffect(() => { setSelected(null); }, [merchantId, values.status, values.duty, values.search, page]);
  const params = { merchantId, search: values.search || undefined, status: values.status || undefined,
    onDuty: values.duty === "ON" ? true : values.duty === "OFF" ? false : undefined, limit: SIZE, offset: (page - 1) * SIZE };
  const query = useQuery({ queryKey: [...KEY, "drivers", params], queryFn: ({ signal }) => listTracking(params, signal), enabled: Boolean(merchantId), refetchInterval: 15000, refetchIntervalInBackground: false });
  const currentSelected = selected && (query.data?.items.find(item => item.id === selected.id) ?? selected);
  const columns: Column<TrackedDriver>[] = [
    { key: "driver", header: "Driver", primary: true, render: item => <span className="row" style={{ flexWrap: "nowrap", gap: 8 }}><UserAvatar name={item.full_name ?? "Driver"} /><span className="cell-stack"><strong>{item.full_name ?? "Name unavailable"}</strong><small>{item.employee_code ?? "No driver code"}</small></span></span> },
    { key: "phone", header: "Mobile", render: item => formatMobileNumber(item.mobile_number) },
    { key: "status", header: "Status", render: item => <span className="cell-stack"><StatusBadge status={item.status} />{item.account_status !== item.status ? <small>Account: {item.account_status}</small> : null}</span> },
    { key: "duty", header: "Duty", render: item => <Badge tone={item.on_duty ? "success" : "neutral"}>{item.on_duty ? "On Duty" : "Off Duty"}</Badge> },
    { key: "position", header: "Latest coordinates", render: item => <span className="cell-stack"><Coordinates latitude={item.current_latitude} longitude={item.current_longitude} /><LocationState driver={item} /></span> },
    { key: "updated", header: "Last location update", render: item => locationTime(item.last_location_at) },
    { key: "duration", header: "Observed at same location", render: item => <ObservedDuration driver={item} /> },
    { key: "actions", header: "Location", render: item => <span className="row" style={{ gap: 4 }}><button className="icon-btn" aria-label={`Open ${item.full_name ?? "driver"} route map`} title="Open route on OpenStreetMap" onClick={() => setSelected(item)}><Icon name="mapPin" size={18} /></button>
      <Button variant="ghost" size="sm" icon="history" disabled={!item.can_view_logs} title={!item.can_view_logs ? "Active, approved, on-duty drivers only" : "Open location history"} onClick={() => setSelected(item)}>Logs</Button></span> }
  ];
  return <div className="page stack">
    <PageHeader title="Live Location Tracking" documentTitle="Live Location Tracking" description="Latest driver GPS observations and on-duty location history."
      actions={<Button variant="secondary" icon="refresh" disabled={!merchantId || query.isFetching} onClick={() => void query.refetch()}>Refresh</Button>} />
    <FilterBar>
      <Field label="Merchant"><Select value={merchantId} onChange={event => setFilter("merchant", event.target.value)} options={[
        { value: "", label: "Select merchant" }, ...(merchants.data?.items ?? []).map(item => ({ value: item.id, label: item.business_name }))
      ]} /></Field>
      <Field label="Driver status"><Select value={values.status} onChange={event => setFilter("status", event.target.value)} options={[
        { value: "", label: "All statuses" }, ...["ACTIVE", "INACTIVE", "PENDING_APPROVAL", "BLOCKED"].map(value => ({ value, label: value.replace(/_/g, " ") }))
      ]} /></Field>
      <Field label="Duty status"><Select value={values.duty} onChange={event => setFilter("duty", event.target.value)} options={[{ value: "", label: "All duty statuses" }, { value: "ON", label: "On Duty" }, { value: "OFF", label: "Off Duty" }]} /></Field>
      <SearchInput label="Search drivers" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search driver name, code or mobile" aria-label="Search drivers" />
    </FilterBar>
    {merchants.error ? <InlineError error={merchants.error} onRetry={() => void merchants.refetch()} /> : null}
    {merchants.isLoading ? <LoadingSkeleton rows={3} label="Loading agencies" /> : !merchantId ? <EmptyState icon="store" title="Select a merchant" description="Choose an agency to view its delivery drivers." /> :
      <Card bodyless className="table-card"><TableHeader title="Delivery drivers" count={query.data?.total} description="Refreshes every 15 seconds while this tab is visible." actions={<RefreshIndicator active={query.isFetching} />} />
        <DataTable caption="Live driver locations" columns={columns} rows={query.error ? undefined : query.data?.items} getRowKey={item => item.id} isLoading={query.isLoading}
          error={query.error} onRetry={() => void query.refetch()} empty={<EmptyState icon="mapPin" title="No matching drivers" description="Change the search, status or duty filters." />}
          footer={<Pagination page={page} pageSize={SIZE} total={query.data?.total ?? 0} onPageChange={setPage} disabled={query.isFetching} itemLabel="drivers" />} />
      </Card>}
    <p className="meta">Updates depend on GPS pings from the delivery app. Locations older than 5 minutes are stale. Same-location duration is observed within 30 metres, stops at a 5-minute ping gap, and never increases beyond the last recorded ping. Observation is limited to the latest 500 points in 24 hours.</p>
    {query.data?.generated_at ? <p className="meta">Last checked: {locationTime(query.data.generated_at)}</p> : null}
    {currentSelected ? <LocationHistory key={`${merchantId}:${currentSelected.id}`} merchantId={merchantId} driver={currentSelected} onClose={() => setSelected(null)} /> : null}
  </div>;
}
