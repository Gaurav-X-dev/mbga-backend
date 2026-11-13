import { GoogleMapLocationPicker } from "../../components/maps/GoogleMapLocationPicker";
import type { Address } from "../../api/orders.api";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listMerchants } from "../../api/merchants.api";
import { createTrip, getLogisticsOptions, getTrip, getTripCandidates, getTrips, optimizeTrip, sequenceTrip, tripAction, type Candidate, type Coordinate, type LogisticsScope, type Trip, type TripActionBody } from "../../api/logistics.api";
import { normalizeError } from "../../api/errors";
import { useAuth } from "../../auth/auth-context";
import { Button } from "../../components/common/Button";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert, EmptyState, ErrorState } from "../../components/feedback/Feedback";
import { Checkbox, Field, Input, Select, Textarea } from "../../components/forms/Field";
import { Card, PageHeader } from "../../components/layout/Page";
import { DataTable, Pagination } from "../../components/tables/DataTable";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import { useUrlFilters } from "../../hooks/useUrlFilters";
import { todayInputValue, humanize } from "../../utils/format";
import "./logistics.css";
export function TripsPage() {
    const auth = useAuth();
    const { values, setFilter } = useUrlFilters(["merchant"] as const);
    const merchant = auth.channel === "merchant";
    const merchantId = merchant ? String(auth.user?.merchant?.id || "") : values.merchant;
    const merchants = useQuery({ queryKey: ["trip-merchants"], queryFn: ({ signal }) => listMerchants({ limit: 100, offset: 0 }, signal), enabled: !merchant && auth.can("merchants.view") });
    return <div className="page stack"><PageHeader title="Trips & routes" description="Plan delivery stops, verify vehicle loads and reconcile returns." actions={!merchant ? <Field label="Merchant" hideLabel><Select placeholder="Select merchant" value={merchantId} options={(merchants.data?.items || []).map(m => ({ value: m.id, label: m.business_name }))} onChange={e => setFilter("merchant", e.target.value)}/></Field> : undefined}/>{merchants.isError ? <ErrorState error={merchants.error} onRetry={() => void merchants.refetch()}/> : null}{merchantId ? <TripWorkspace key={merchantId} scope={{ merchant, merchantId }}/> : <Card><EmptyState title="Select a merchant to load trips"/></Card>}</div>;
}
function TripWorkspace({ scope }: {
    scope: LogisticsScope;
}) {
    const auth = useAuth();
    const cache = useQueryClient();
    const [page, setPage] = useState(1);
    const [status, setStatus] = useState("");
    const [vehicle, setVehicle] = useState("");
    const term = useDebouncedValue(vehicle.trim());
    const [createOpen, setCreateOpen] = useState(false);
    const [tripId, setTripId] = useState("");
    const options = useQuery({ queryKey: ["logistics", "options", scope], queryFn: ({ signal }) => getLogisticsOptions(scope, signal) });
    const trips = useQuery({ queryKey: ["logistics", "trips", scope, page, status, term], queryFn: ({ signal }) => getTrips(scope, { limit: 20, offset: (page - 1) * 20, status: status || undefined, vehicle: term || undefined }, signal) });
    return <><Card title="Trip register"><div className="logistics-actions"><Field label="Status"><Select value={status} placeholder="All statuses" options={["ACTIVE", "DRAFT", "READY", "IN_PROGRESS", "RETURNED", "DISCREPANCY", "RECONCILED", "CANCELLED"].map(value => ({ value, label: humanize(value) }))} onChange={e => { setStatus(e.target.value); setPage(1); }}/></Field><Field label="Vehicle number"><Input maxLength={50} value={vehicle} placeholder="Exact registration number" onChange={e => { setVehicle(e.target.value); setPage(1); }}/></Field>{auth.can("delivery.confirm") ? <Button onClick={() => setCreateOpen(true)} disabled={!options.data}>Plan trip</Button> : null}<Link to={`${scope.merchant ? '/merchant' : '/admin'}/reports?type=VEHICLE_DISPATCH_RETURN&merchant=${encodeURIComponent(scope.merchantId)}`}>Vehicle dispatch & returns report</Link></div>
 {options.isError ? <ErrorState error={options.error} onRetry={() => void options.refetch()}/> : null}<DataTable caption="Trips" rows={trips.data?.items} getRowKey={r => r.id} isLoading={trips.isLoading} error={trips.error} onRetry={() => void trips.refetch()} empty={<EmptyState title="No trips" description="Confirm orders and assign their deliveries before planning a trip."/>} columns={[{ key: "number", header: "Trip", primary: true, render: r => <Button variant="link" onClick={() => setTripId(r.id)}>{r.number}</Button> }, { key: "date", header: "Date", render: r => r.date }, { key: "vehicleNumber", header: "Vehicle", render: r => r.vehicleNumber }, { key: "driverName", header: "Driver", render: r => r.driverName }, { key: "stops", header: "Stops", render: r => r.stops.length }, { key: "status", header: "Status", render: r => humanize(r.status) }]} footer={<Pagination page={page} pageSize={20} total={trips.data?.total || 0} onPageChange={setPage} itemLabel="trips"/>}/></Card>
 {createOpen && options.data ? <CreateTrip scope={scope} config={options.data.policy} onClose={() => setCreateOpen(false)} onCreated={id => { setTripId(id); void cache.invalidateQueries({ queryKey: ["logistics"] }); }}/> : null}
 {tripId ? <TripDetail key={tripId} scope={scope} id={tripId} onClose={() => setTripId("")}/> : null}</>;
}
function CreateTrip({ scope, config, onClose, onCreated }: {
    scope: LogisticsScope;
    config: import('../../api/logistics.api').LogisticsPolicy;
    onClose: () => void;
    onCreated: (id: string) => void;
}) {
    const [priority, setPriority] = useState("");
    const [date, setDate] = useState(todayInputValue());
    const [search, setSearch] = useState("");
    const term = useDebouncedValue(search.trim());
    const [page, setPage] = useState(1);
    const [selected, setSelected] = useState<Record<string, Candidate>>({});
    const [notes, setNotes] = useState("");
    const [key] = useState(() => crypto.randomUUID());
    const [origin, setOrigin] = useState({ latitude: config.defaultOrigin ? String(config.defaultOrigin.latitude) : "", longitude: config.defaultOrigin ? String(config.defaultOrigin.longitude) : "" });
    const [destination, setDestination] = useState({ latitude: config.defaultDestination ? String(config.defaultDestination.latitude) : "", longitude: config.defaultDestination ? String(config.defaultDestination.longitude) : "" });
    const candidates = useQuery({ queryKey: ["logistics", "candidates", scope, term, page, priority, date], queryFn: ({ signal }) => getTripCandidates(scope, term, page, signal, priority, date) });
    const rows = Object.values(selected);
    const first = rows[0];
    const coordinate = (p: typeof origin): Coordinate | undefined => p.latitude !== "" && p.longitude !== "" && Number.isFinite(Number(p.latitude)) && Number.isFinite(Number(p.longitude)) ? { latitude: Number(p.latitude), longitude: Number(p.longitude) } : undefined;
    const valid = date >= todayInputValue() && rows.length > 0 && Boolean(coordinate(origin)) && ((destination.latitude === "" && destination.longitude === "") || Boolean(coordinate(destination)));
    const save = useMutation({ mutationFn: () => createTrip(scope, { deliveryIds: rows.map(r => r.deliveryId), origin: coordinate(origin), destination: coordinate(destination) || coordinate(origin), idempotencyKey: key, notes: notes.trim() || undefined }), onSuccess: r => { onCreated(r.id); onClose(); } });
    return <Modal open wide title="Plan a trip" onClose={onClose} busy={save.isPending}><form className="stack" onSubmit={e => {
            e.preventDefault();
            if (valid)
                save.mutate();
        }}><p className="meta">Choose scheduled deliveries for one vehicle, driver and date. Up to {config.maxStops} stops. Delivery addresses must be checked before road optimization.</p><Field label="Find scheduled deliveries"><Input maxLength={120} value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} placeholder="Customer, order, vehicle or driver"/></Field>
 <div className="form-grid"><Field label="Delivery date"><Input type="date" min={todayInputValue()} value={date} onChange={e => { setDate(e.target.value); setPage(1); setSelected({}); }}/></Field><Field label="Priority filter"><Select value={priority} placeholder="All priorities" options={config.priorities.map(p => ({ value: p.code, label: p.label }))} onChange={e => { setPriority(e.target.value); setPage(1); }}/></Field></div>
 <div className="logistics-stops">{(candidates.data?.items || []).map(c => {
            const incompatible = Boolean(first && (first.vehicleNumber !== c.vehicleNumber || first.driverUserId !== c.driverUserId || first.date !== c.date));
            return <Checkbox key={c.deliveryId} label={`${c.orderNumber} · ${c.customerName}`} description={`${config.priorities.find(p => p.code === c.priorityCode)?.label || c.priorityCode || ""} · ${c.vehicleNumber} · ${c.driverName} · ${c.date} · ${c.itemsSummary}`} checked={Boolean(selected[c.deliveryId])} disabled={incompatible || !c.driverUserId || (!selected[c.deliveryId] && rows.length >= config.maxStops) || candidates.isFetching || search.trim() !== term} onChange={e => {
                    const checked = e.target.checked;
                    setSelected(old => {
                        const next = { ...old };
                        if (checked)
                            next[c.deliveryId] = c;
                        else
                            delete next[c.deliveryId];
                        return next;
                    });
                }}/>;
        })}</div>
 {candidates.isError ? <ErrorState error={candidates.error} onRetry={() => void candidates.refetch()}/> : null}{candidates.data?.total === 0 ? <p>No eligible scheduled deliveries. Confirm and assign orders first.</p> : null}<Pagination page={page} pageSize={20} total={candidates.data?.total || 0} onPageChange={setPage} itemLabel="deliveries"/><div className="logistics-actions"><strong>{rows.length} stops selected</strong>{rows.length ? <Button variant="secondary" onClick={() => setSelected({})}>Clear selected stops</Button> : null}</div>
 {([['Dispatch point', origin, setOrigin], ['Return point (blank = dispatch point)', destination, setDestination]] as const).map(([label, value, set]) => <div className="form-grid" key={label}><Field label={`${label} latitude`}><Input type="number" step="any" min={-90} max={90} required={label === 'Dispatch point'} value={value.latitude} onChange={e => set({ ...value, latitude: e.target.value })}/></Field><Field label="Longitude"><Input type="number" step="any" min={-180} max={180} required={label === 'Dispatch point'} value={value.longitude} onChange={e => set({ ...value, longitude: e.target.value })}/></Field></div>)}
 <Field label="Planning notes"><Textarea maxLength={2000} value={notes} onChange={e => setNotes(e.target.value)}/></Field>{save.isError ? <Alert tone="error">{normalizeError(save.error).userMessage}</Alert> : null}<Button type="submit" loading={save.isPending} disabled={!valid}>Create draft trip</Button></form></Modal>;
}
function TripDetail({ scope, id, onClose }: {
    scope: LogisticsScope;
    id: string;
    onClose: () => void;
}) {
    const auth = useAuth();
    const cache = useQueryClient();
    const [dialog, setDialog] = useState<{
        action: string;
        trip: Trip;
    } | null>(null);
    const [reorder, setReorder] = useState<string[] | null>(null);
    const [pins, setPins] = useState<string[] | null>(null);
    const [reason, setReason] = useState("");
    const [pinStop, setPinStop] = useState<string | null>(null);
    const query = useQuery({ queryKey: ["logistics", "trip", scope, id], queryFn: ({ signal }) => getTrip(scope, id, signal), refetchInterval: 15000 });
    const options = useQuery({ queryKey: ["logistics", "options", scope], queryFn: ({ signal }) => getLogisticsOptions(scope, signal) });
    const trip = query.data;
    const changed = async () => { setReorder(null); setPins(null); setReason(""); await cache.invalidateQueries({ queryKey: ["logistics"] }); await cache.invalidateQueries({ queryKey: ["deliveries"] }); await cache.invalidateQueries({ queryKey: ["orders"] }); await cache.invalidateQueries({ queryKey: ["inventory"] }); await cache.invalidateQueries({ queryKey: ["reports"] }); };
    const sequence = useMutation({ mutationFn: (ids: string[]) => sequenceTrip(scope, id, { deliveryIds: ids, pinnedDeliveryIds: pins || trip!.stops.filter(s => s.pinned).map(s => s.deliveryId), expectedVersion: trip!.version, reason: reason.trim() }), onSuccess: changed });
    const optimize = useMutation({ mutationFn: () => optimizeTrip(scope, id, trip!.version, reason.trim()), onSuccess: changed });
    const move = (index: number, delta: number) => { const ids = [...(reorder || trip!.stops.map(s => s.deliveryId))]; [ids[index], ids[index + delta]] = [ids[index + delta], ids[index]]; setReorder(ids); };
    return <Modal open wide title={trip ? `${trip.number} · ${trip.vehicleNumber}` : "Trip details"} onClose={onClose} busy={Boolean(dialog || pinStop)}>{query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()}/> : !trip ? <p>Loading trip…</p> : <div className="stack"><p>{trip.driverName} · {trip.date} · <strong>{humanize(trip.status)}</strong></p>{trip.notes ? <p className="meta">{trip.notes}</p> : null}<p className="meta">Plan → verify actual load → start trip → complete deliveries → submit vehicle return → office verification. Cash handovers remain in the separate cash collection module.</p>
 <div className="logistics-actions">{auth.can("delivery.confirm") ? ({ DRAFT: ["READY", "CANCEL"], READY: ["START", "DRAFT"], IN_PROGRESS: ["RETURN"], RETURNED: ["VERIFY"], DISCREPANCY: ["VERIFY", ...(auth.can("inventory.adjust") ? ["RESOLVE"] : [])] } as Record<string, string[]>)[trip.status]?.filter(action => !trip.verificationBlockedReason || !["VERIFY", "RESOLVE"].includes(action)).map(action => <Button key={action} variant={action === 'RESOLVE' ? 'danger' : 'secondary'} onClick={() => setDialog({ action, trip })}>{({ READY: 'Verify loading', START: 'Start trip', DRAFT: 'Reset unstarted load', RETURN: 'Submit vehicle return', VERIFY: 'Verify physical returns', RESOLVE: 'Resolve with stock adjustment', CANCEL: 'Cancel draft' } as Record<string, string>)[action]}</Button>) : null}<Link to={`${scope.merchant ? '/merchant' : '/admin'}/reports?type=VEHICLE_DISPATCH_RETURN&merchant=${scope.merchantId}&tripId=${trip.id}&tripDateBasis=scheduled&range=custom&from=${trip.date}&to=${trip.date}`}>Download / view report</Link></div>
 {trip.verificationBlockedReason && ["RETURNED", "DISCREPANCY"].includes(trip.status) ? <Alert tone="warning">{trip.verificationBlockedReason}</Alert> : null}
 <div className="logistics-stops">{(reorder || trip.stops.map(s => s.deliveryId)).map((sid, index) => {
                const s = trip.stops.find(v => v.deliveryId === sid)!;
                return <div className="logistics-stop" key={sid}><strong>{index + 1}</strong><div className="cell-stack"><strong>{s.customerName} · {s.orderNumber}</strong><span>{s.address}</span><small>{s.itemsSummary} · {humanize(s.status)}</small></div>{s.priority ? <span className="logistics-priority" style={{ borderColor: s.priority.color, color: "var(--text)" }}>{s.priority.label}</span> : null}{s.latitude !== null && s.longitude !== null ? <a href={`https://www.google.com/maps/dir/?api=1&destination=${s.latitude},${s.longitude}`} target="_blank" rel="noreferrer">Navigate</a> : <small>Coordinates missing</small>}{auth.can("delivery.confirm") && ['DRAFT', 'READY', 'IN_PROGRESS'].includes(trip.status) ? <><Button size="sm" variant="secondary" disabled={index === 0} onClick={() => move(index, -1)}>↑</Button><Button size="sm" variant="secondary" disabled={index === trip.stops.length - 1} onClick={() => move(index, 1)}>↓</Button><Button size="sm" variant="secondary" onClick={() => setPinStop(sid)}>Edit map pin</Button><Checkbox label="Fix stop position" checked={(pins || trip.stops.filter(s => s.pinned).map(s => s.deliveryId)).includes(sid)} onChange={e => {
                            const next = new Set(pins || trip.stops.filter(s => s.pinned).map(s => s.deliveryId));
                            if (e.target.checked)
                                next.add(sid);
                            else
                                next.delete(sid);
                            setPins([...next]);
                        }}/></> : null}</div>;
            })}</div>
 {auth.can("delivery.confirm") && ['DRAFT', 'READY', 'IN_PROGRESS'].includes(trip.status) ? <><Field label="Reason for sequence / optimization change"><Textarea minLength={3} maxLength={2000} value={reason} onChange={e => setReason(e.target.value)}/></Field><div className="logistics-actions"><Button disabled={(!reorder && !pins) || reason.trim().length < 3} loading={sequence.isPending} onClick={() => sequence.mutate(reorder || trip.stops.map(s => s.deliveryId))}>Save stop sequence</Button>{trip.status !== 'IN_PROGRESS' ? <Button variant="secondary" disabled={!options.data?.routingConfigured || !options.data.policy.optimizationEnabled || reason.trim().length < 3} loading={optimize.isPending} onClick={() => optimize.mutate()}>Preview optimized route</Button> : null}</div>{!options.data?.routingConfigured || !options.data.policy.optimizationEnabled ? <p className="meta">Manual sequencing is available. Road optimization requires provider configuration and an enabled policy in App Settings.</p> : null}</> : null}
 {trip.route ? <Alert tone="info">Estimated road distance: {trip.route.distanceMeters != null ? `${(trip.route.distanceMeters / 1000).toFixed(1)} km` : 'Unavailable'} · {trip.route.approved ? 'Accepted route' : 'Preview — review the proposed order below before accepting.'}{!trip.route.approved && auth.can("delivery.confirm") ? <><ol>{trip.route.deliveryIds.map(sid => <li key={sid}>{trip.stops.find(s => s.deliveryId === sid)?.customerName}</li>)}</ol><Field label="Reason to accept route"><Input minLength={3} value={reason} onChange={e => setReason(e.target.value)}/></Field><Button disabled={reason.trim().length < 3} loading={sequence.isPending} onClick={() => sequence.mutate(trip.route!.deliveryIds)}>Accept proposed sequence</Button></> : null}</Alert> : null}
 {sequence.isError || optimize.isError ? <Alert tone="error">{normalizeError(sequence.error || optimize.error).userMessage}</Alert> : null}
 <Card title="Vehicle load & return reconciliation"><div className="table-wrap"><table className="data-table"><thead><tr><th>Cylinder</th><th>Loaded filled</th><th>Delivered</th><th>Pending</th><th>Unfulfilled</th><th>Expected filled return</th><th>Expected empties</th></tr></thead><tbody>{trip.lines.map(l => <tr key={l.cylinderType}><td>{options.data?.cylinders.find(c => c.code === l.cylinderType)?.label || l.cylinderType}</td><td>{l.loadedFilled}</td><td>{l.delivered}</td><td>{l.pending ?? "—"}</td><td>{l.unfulfilled}</td><td>{l.expectedFilled}</td><td>{l.expectedEmpty}</td></tr>)}</tbody></table></div>{trip.returnSubmission ? <p>Driver return submitted: {trip.returnSubmission.reason}</p> : null}{trip.verification ? <><p>Office verification: {trip.verification.reason}</p>{trip.verification.differences.map(d => <p key={d.cylinderType}>{d.cylinderType}: filled difference {d.filledDifference}, empty difference {d.emptyDifference}, damaged filled {d.damaged}</p>)}</> : null}{trip.status === 'DISCREPANCY' ? <Alert tone="warning">The vehicle remains unreconciled. Recount and verify, or an authorized inventory user can explicitly resolve the recorded shortage/damage with audited stock adjustments.</Alert> : null}</Card>
 </div>}{pinStop && trip ? <TripPinDialog scope={scope} trip={trip} stopId={pinStop} onClose={() => setPinStop(null)} onSaved={() => { setPinStop(null); void changed(); }}/> : null}{dialog ? <TripActionDialog key={`${dialog.action}-${dialog.trip.version}`} scope={scope} trip={dialog.trip} action={dialog.action} requireOdometer={options.data?.policy.requireOdometer || false} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); void changed(); }}/> : null}</Modal>;
}
function TripActionDialog({ scope, trip, action, requireOdometer, onClose, onSaved }: {
    scope: LogisticsScope;
    trip: Trip;
    action: string;
    requireOdometer: boolean;
    onClose: () => void;
    onSaved: () => void;
}) {
    const [reason, setReason] = useState("");
    const [odometer, setOdometer] = useState("");
    const [confirm, setConfirm] = useState(false);
    const [counts, setCounts] = useState<Record<string, {
        a: string;
        b: string;
        c: string;
    }>>(Object.fromEntries(trip.lines.map(l => [l.cylinderType, { a: action === 'READY' ? String(l.planned) : '', b: action === 'READY' ? '0' : '', c: '0' }])));
    const needsCounts = ['READY', 'RETURN', 'VERIFY', 'RESOLVE'].includes(action);
    const needsOdo = ['START', 'RETURN'].includes(action);
    const validCount = Object.values(counts).every(l => [l.a, l.b, l.c].every(v => /^\d+$/.test(v) && Number(v) <= 100000));
    const valid = reason.trim().length >= 3 && (!needsCounts || validCount) && (!needsOdo || !requireOdometer || /^\d+$/.test(odometer)) && (!['RESOLVE', 'DRAFT'].includes(action) || confirm);
    const save = useMutation({ mutationFn: () => {
            const body: TripActionBody = { action, expectedVersion: trip.version, reason: reason.trim() };
            if (action === 'DRAFT')
                body.confirmedUnloaded = confirm;
            if (needsOdo && odometer !== '')
                body.odometer = Number(odometer);
            if (action === 'READY')
                body.loads = Object.entries(counts).map(([c, l]) => ({ cylinderType: c, loadedFilled: Number(l.a), openingEmpty: Number(l.b) }));
            else if (needsCounts)
                body.counts = Object.entries(counts).map(([c, l]) => ({ cylinderType: c, filled: Number(l.a), empty: Number(l.b), damaged: Number(l.c) }));
            return tripAction(scope, trip.id, body);
        }, onSuccess: onSaved });
    return <Modal open wide title={`${humanize(action)} · ${trip.number}`} onClose={onClose} busy={save.isPending}><form className="stack" onSubmit={e => {
            e.preventDefault();
            if (valid)
                save.mutate();
        }}>{action === 'READY' ? <p>Count the actual filled/empty load before confirming. The load must cover planned allocations. Inventory ownership totals will not be increased.</p> : needsCounts ? <p>Enter actual physical counts for every cylinder type, including zero. Damaged counts here mean damaged filled cylinders, separate from usable filled returns.</p> : <p>Confirm this trip action after checking the vehicle and current delivery state.</p>}
 {needsCounts ? trip.lines.map(l => <div className="logistics-counts" key={l.cylinderType}><strong>{l.cylinderType}<small className="meta"> · {action === 'READY' ? `Planned ${l.planned}` : `Expected filled ${l.expectedFilled}, empty ${l.expectedEmpty}`}</small></strong>{(['a', 'b', ...(action === 'READY' ? [] : ['c'])] as Array<'a' | 'b' | 'c'>).map((key, index) => <Field key={key} label={action === 'READY' ? (index === 0 ? 'Actual filled loaded' : 'Opening empties') : (['Actual filled returned', 'Actual empties returned', 'Damaged filled returned'][index])}><Input type="number" min={0} max={100000} step={1} required value={counts[l.cylinderType][key]} onChange={e => setCounts({ ...counts, [l.cylinderType]: { ...counts[l.cylinderType], [key]: e.target.value } })}/></Field>)}</div>) : null}
 {needsOdo ? <Field label="Odometer reading (km)"><Input type="number" min={trip.startOdometer ?? 0} max={100000000} step={1} required={requireOdometer} value={odometer} onChange={e => setOdometer(e.target.value)}/></Field> : null}<Field label="Reason / verification notes"><Textarea minLength={3} maxLength={2000} required value={reason} onChange={e => setReason(e.target.value)}/></Field>{action === 'DRAFT' ? <Checkbox label="I confirm every filled and empty cylinder was physically unloaded back to the depot." checked={confirm} onChange={e => setConfirm(e.target.checked)}/> : null}{action === 'RESOLVE' ? <Checkbox label="I confirm these verified counts and authorize the corresponding audited stock corrections." checked={confirm} onChange={e => setConfirm(e.target.checked)}/> : null}{save.isError ? <Alert tone="error">{normalizeError(save.error).userMessage}</Alert> : null}<Button type="submit" variant={action === 'RESOLVE' ? 'danger' : 'primary'} disabled={!valid} loading={save.isPending}>Confirm {humanize(action)}</Button></form></Modal>;
}
function TripPinDialog({ scope, trip, stopId, onClose, onSaved }: {
    scope: LogisticsScope;
    trip: Trip;
    stopId: string;
    onClose: () => void;
    onSaved: () => void;
}) {
    const stop = trip.stops.find(s => s.deliveryId === stopId)!;
    const [latitude, setLatitude] = useState(stop.latitude == null ? "" : String(stop.latitude));
    const [longitude, setLongitude] = useState(stop.longitude == null ? "" : String(stop.longitude));
    const [reason, setReason] = useState("");
    const [map, setMap] = useState(false);
    const [address, setAddress] = useState<Address>({ line1: stop.address, latitude: stop.latitude, longitude: stop.longitude });
    const valid = latitude !== "" && longitude !== "" && Number.isFinite(Number(latitude)) && Number.isFinite(Number(longitude)) && Math.abs(Number(latitude)) <= 90 && Math.abs(Number(longitude)) <= 180 && reason.trim().length >= 3;
    const save = useMutation({ mutationFn: () => sequenceTrip(scope, trip.id, { deliveryIds: trip.stops.map(s => s.deliveryId), pinnedDeliveryIds: trip.stops.filter(s => s.pinned).map(s => s.deliveryId), coordinates: [{ deliveryId: stopId, latitude: Number(latitude), longitude: Number(longitude) }], expectedVersion: trip.version, reason: reason.trim() }), onSuccess: onSaved });
    return <Modal open wide title={`Trip map pin · ${stop.customerName}`} onClose={onClose} busy={save.isPending}><form className="stack" onSubmit={e => {
            e.preventDefault();
            if (valid)
                save.mutate();
        }}><p className="meta">Check the actual delivery entrance. This updates this trip’s navigation pin and invalidates its route preview; it does not rewrite the customer address or historical order.</p><Button variant="secondary" onClick={() => setMap(!map)}>{map ? "Hide map picker" : "Choose using existing map picker"}</Button>{map ? <GoogleMapLocationPicker value={address} onChange={next => { setAddress(next); setLatitude(next.latitude == null ? "" : String(next.latitude)); setLongitude(next.longitude == null ? "" : String(next.longitude)); }} merchantId={scope.merchantId} locationChannel={scope.merchant ? "merchant" : "admin"} postalOnly prefix="Trip navigation"/> : null}<div className="form-grid"><Field label="Delivery entrance latitude"><Input required type="number" step="any" min={-90} max={90} value={latitude} onChange={e => setLatitude(e.target.value)}/></Field><Field label="Delivery entrance longitude"><Input required type="number" step="any" min={-180} max={180} value={longitude} onChange={e => setLongitude(e.target.value)}/></Field></div><Field label="Reason for pin correction"><Textarea required minLength={3} maxLength={2000} value={reason} onChange={e => setReason(e.target.value)}/></Field>{save.isError ? <Alert tone="error">{normalizeError(save.error).userMessage}</Alert> : null}<Button type="submit" disabled={!valid} loading={save.isPending}>Save reviewed trip pin</Button></form></Modal>;
}
