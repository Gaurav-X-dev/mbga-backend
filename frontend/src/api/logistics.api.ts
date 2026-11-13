import { apiClient } from "./client";
import { cleanParams } from "./params";
export type LogisticsScope = {
    merchant: boolean;
    merchantId: string;
};
export type PriorityOption = {
    code: string;
    label: string;
    rank: number;
    color: string;
};
export type Coordinate = {
    latitude: number;
    longitude: number;
};
export type LogisticsPolicy = {
    priorities: PriorityOption[];
    defaultPriority: string;
    maxStops: number;
    maxLoadCylinders: number;
    optimizationEnabled: boolean;
    priorityFirst: boolean;
    requireSeparateReturnVerifier: boolean;
    requireOdometer: boolean;
    defaultOrigin: Coordinate | null;
    defaultDestination: Coordinate | null;
};
export type TripLine = {
    pending?: number;
    cylinderType: string;
    planned: number;
    delivered: number;
    collectedEmpty: number;
    loadedFilled: number;
    openingEmpty: number;
    expectedFilled: number;
    expectedEmpty: number;
    unfulfilled: number;
};
export type TripStop = {
    deliveryId: string;
    orderId: string;
    orderNumber: string;
    customerName: string;
    address: string;
    latitude: number | null;
    longitude: number | null;
    sequence: number;
    pinned: boolean;
    status: string;
    priorityCode: string | null;
    priority: PriorityOption | null;
    itemsSummary: string;
};
export type ReturnCount = {
    cylinderType: string;
    filled: number;
    empty: number;
    damaged: number;
};
export type Trip = {
    verificationBlockedReason?: string | null;
    id: string;
    number: string;
    version: number;
    vehicleNumber: string;
    driverUserId: string;
    driverName: string;
    date: string;
    status: string;
    stops: TripStop[];
    lines: TripLine[];
    notes: string | null;
    origin: Coordinate;
    destination: Coordinate;
    startOdometer: number | null;
    endOdometer: number | null;
    distanceKm: number | null;
    route: {
        deliveryIds: string[];
        distanceMeters?: number;
        duration?: string;
        approved: boolean;
        basedOnVersion: number;
    } | null;
    returnSubmission: {
        counts: ReturnCount[];
        reason: string;
    } | null;
    verification: {
        counts: ReturnCount[];
        differences: Array<{
            cylinderType: string;
            filledDifference: number;
            emptyDifference: number;
            damaged: number;
        }>;
        reason: string;
        adjustmentsApplied: boolean;
    } | null;
};
export type Candidate = {
    priorityCode?: string | null;
    deliveryId: string;
    customerName: string;
    vehicleNumber: string;
    driverUserId: string;
    driverName: string;
    date: string;
    orderNumber: string;
    itemsSummary: string;
};
const base = (s: LogisticsScope) => `/${s.merchant ? "merchant" : "admin"}/trips`;
const params = (s: LogisticsScope, extra: object = {}) => cleanParams({ ...(!s.merchant ? { merchantId: s.merchantId } : {}), ...extra });
export async function getLogisticsOptions(s: LogisticsScope, signal?: AbortSignal) {
    return (await apiClient.get<{
        policy: LogisticsPolicy;
        routingConfigured: boolean;
        cylinders: Array<{
            code: string;
            label: string;
        }>;
    }>(`${base(s)}/options`, { params: params(s), signal })).data;
}
export async function getTrips(s: LogisticsScope, filters: object, signal?: AbortSignal) {
    return (await apiClient.get<{
        items: Trip[];
        total: number;
    }>(base(s), { params: params(s, filters), signal })).data;
}
export async function getTrip(s: LogisticsScope, id: string, signal?: AbortSignal) { return (await apiClient.get<Trip>(`${base(s)}/${id}`, { params: params(s), signal })).data; }
export async function getTripCandidates(s: LogisticsScope, search: string, page: number, signal?: AbortSignal, priorityCode?: string, deliveryDate?: string) {
    return (await apiClient.get<{
        items: Candidate[];
        total: number;
    }>(`${base(s)}/candidates`, { params: params(s, { search, priorityCode: priorityCode || undefined, deliveryDate: deliveryDate || undefined, limit: 20, offset: (page - 1) * 20 }), signal })).data;
}
export async function createTrip(s: LogisticsScope, body: {
    deliveryIds: string[];
    origin?: Coordinate;
    destination?: Coordinate;
    idempotencyKey: string;
    notes?: string;
}) { return (await apiClient.post<Trip>(base(s), body, { params: params(s) })).data; }
export async function sequenceTrip(s: LogisticsScope, id: string, body: {
    deliveryIds: string[];
    pinnedDeliveryIds: string[];
    coordinates?: Array<Coordinate & {
        deliveryId: string;
    }>;
    expectedVersion: number;
    reason: string;
}) { return (await apiClient.patch<Trip>(`${base(s)}/${id}/sequence`, body, { params: params(s) })).data; }
export async function optimizeTrip(s: LogisticsScope, id: string, expectedVersion: number, reason: string) { return (await apiClient.post<Trip>(`${base(s)}/${id}/optimize`, { expectedVersion, reason }, { params: params(s) })).data; }
export type TripActionBody = {
    confirmedUnloaded?: boolean;
    action: string;
    expectedVersion: number;
    reason: string;
    loads?: Array<{
        cylinderType: string;
        loadedFilled: number;
        openingEmpty: number;
    }>;
    counts?: ReturnCount[];
    odometer?: number;
};
export async function tripAction(s: LogisticsScope, id: string, body: TripActionBody) { return (await apiClient.post<Trip>(`${base(s)}/${id}/actions`, body, { params: params(s) })).data; }
export async function getLogisticsSettings(merchantId?: string, signal?: AbortSignal) {
    return (await apiClient.get<{
        config: LogisticsPolicy;
        routingConfigured: boolean;
    }>("/admin/logistics/settings", { params: cleanParams({ merchantId }), signal })).data;
}
export async function saveLogisticsSettings(merchantId: string | undefined, config: LogisticsPolicy | null) { return (await apiClient.patch("/admin/logistics/settings", { config }, { params: cleanParams({ merchantId }) })).data; }
