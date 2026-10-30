import { apiClient } from "./client";
import { cleanParams } from "./params";
import type { DeliveryMember } from "./delivery-team.api";

export type TrackedDriver = DeliveryMember & {
  account_status: string;
  can_view_logs: boolean;
  current_latitude: number | null;
  current_longitude: number | null;
  location_accuracy: number | null;
  last_location_at: string | null;
  location_state: "UNAVAILABLE" | "UNKNOWN_TIME" | "RECENT" | "STALE" | "FUTURE";
  stationary_seconds: number | null;
  stationary_since: string | null;
  stationary_until: string | null;
  stationary_sample_count: number;
  stationary_is_lower_bound: boolean;
};
export type TrackingParams = { merchantId: string; search?: string; status?: string; onDuty?: boolean; limit: number; offset: number };
export type TrackingList = { items: TrackedDriver[]; total: number; limit: number; offset: number; generated_at: string;
  policy: { stationary_radius_metres: number; max_ping_gap_seconds: number; stale_after_seconds: number; observation_hours: number; point_limit: number } };
export type LocationLog = { id: string; latitude: number; longitude: number; accuracy: number | null; recorded_at: string; received_at: string; is_future: boolean };
export type HistoryParams = { merchantId: string; fromDate: string; toDate: string; limit: number; offset: number };
export type TrackingHistory = { driver: TrackedDriver; items: LocationLog[]; total: number; limit: number; offset: number; from_date: string; to_date: string; generated_at: string };
export async function listTracking(params: TrackingParams, signal?: AbortSignal) {
  return (await apiClient.get<TrackingList>("/admin/live-location", { params: cleanParams(params), signal })).data;
}
export async function getLocationLogs(driverId: string, params: HistoryParams, signal?: AbortSignal) {
  return (await apiClient.get<TrackingHistory>(`/admin/live-location/${encodeURIComponent(driverId)}/logs`, { params: cleanParams(params), signal })).data;
}

export type TrackingRoute = { items: LocationLog[]; total: number; limit: number; truncated: boolean; from_date: string; to_date: string; generated_at: string; stationary_radius_metres: number; max_ping_gap_seconds: number };
export async function getTrackingRoute(driverId: string, params: Omit<HistoryParams, "limit" | "offset">, signal?: AbortSignal) {
  return (await apiClient.get<TrackingRoute>(`/admin/live-location/${encodeURIComponent(driverId)}/route`, { params: cleanParams(params), signal })).data;
}
