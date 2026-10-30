import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listMerchants } from "../../api/merchants.api";
import { getLocationLogs, getTrackingRoute, listTracking, type TrackedDriver, type TrackingList } from "../../api/live-location.api";
import { AppError } from "../../api/errors";
import { LiveLocationPage } from "./LiveLocationPage";
import { duration, locationTime, mapsUrl } from "./tracking-utils";

vi.mock("../../api/live-location.api", () => ({ listTracking: vi.fn(), getLocationLogs: vi.fn(), getTrackingRoute: vi.fn() }));
vi.mock("../../api/merchants.api", () => ({ listMerchants: vi.fn() }));
vi.mock("./DriverRouteMap", () => ({ default: () => <div aria-label="Driver route on OpenStreetMap" /> }));
const driver: TrackedDriver = {
  id: "driver", merchant_id: "merchant", user_id: "user", delivery_user_type: "DRIVER",
  full_name: "Raman", mobile_number: "+919876543210", email: null, employee_code: "DRV-1",
  driving_license_number: null, driving_license_expiry: null, address: null, status: "ACTIVE",
  approval_status: "APPROVED", role: "driver", allowed_channel: "DELIVERY", on_duty: true,
  created_at: "2026-10-29T00:00:00Z", account_status: "ACTIVE", can_view_logs: true,
  current_latitude: 28.418512, current_longitude: 77.037745, location_accuracy: 5,
  last_location_at: "2026-10-29T15:35:00+05:30", location_state: "RECENT",
  stationary_seconds: 120, stationary_since: "2026-10-29T15:33:00+05:30",
  stationary_until: "2026-10-29T15:35:00+05:30", stationary_sample_count: 3, stationary_is_lower_bound: false
};
const response: TrackingList = { items: [driver], total: 1, limit: 20, offset: 0,
  generated_at: "2026-10-29T15:35:00+05:30", policy: { stationary_radius_metres: 30,
    max_ping_gap_seconds: 300, stale_after_seconds: 300, observation_hours: 24, point_limit: 500 } };
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getTrackingRoute).mockResolvedValue({ items: [], total: 0, limit: 10000, truncated: false, from_date: "2026-10-29", to_date: "2026-10-29", generated_at: response.generated_at, stationary_radius_metres: 30, max_ping_gap_seconds: 300 });
  vi.mocked(listMerchants).mockResolvedValue({ items: [{ id: "merchant", business_name: "Agency" }], total: 1, limit: 100, offset: 0 } as Awaited<ReturnType<typeof listMerchants>>);
  vi.mocked(listTracking).mockResolvedValue(response);
  vi.mocked(getLocationLogs).mockResolvedValue({ driver, items: [{ id: "log", latitude: 28.418512, longitude: 77.037745,
    recorded_at: "2026-10-29T15:35:00+05:30", received_at: "2026-10-29T15:35:01+05:30", accuracy: 5, is_future: false }],
    total: 1, limit: 50, offset: 0, from_date: "2026-10-29", to_date: "2026-10-29", generated_at: response.generated_at });
});
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { client, ...render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/admin/live-location?merchant=merchant"]}><LiveLocationPage /></MemoryRouter></QueryClientProvider>) };
}

describe("Live Location Tracking", () => {
  it("opens the OpenStreetMap route from the driver map icon", async () => {
    mount();
    const table = within(await screen.findByRole("table", { name: "Live driver locations" }));
    expect(table.getByText("Raman")).toBeInTheDocument();
    expect(table.getByText("DRV-1")).toBeInTheDocument();
    expect(table.getByText("2m 0s")).toBeInTheDocument();
    await userEvent.click(table.getByRole("button", { name: "Open Raman route map" }));
    expect(await screen.findByLabelText("Driver route on OpenStreetMap")).toBeInTheDocument();
    expect(getTrackingRoute).toHaveBeenCalledWith("driver", expect.objectContaining({ merchantId: "merchant" }), expect.anything());
    expect(table.getByText("Recent ping")).toBeInTheDocument();
  });
  it("opens paginated logs with recorded coordinates and explicit IST timestamps", async () => {
    mount(); const user = userEvent.setup();
    const table = within(await screen.findByRole("table", { name: "Live driver locations" }));
    await user.click(table.getByRole("button", { name: "Logs" }));
    const panel = await screen.findByRole("dialog");
    await waitFor(() => expect(getLocationLogs).toHaveBeenCalledWith("driver", expect.objectContaining({ merchantId: "merchant", limit: 50, offset: 0 }), expect.anything()));
    expect(within(await within(panel).findByRole("table", { name: "Driver location history" })).getByRole("link", { name: "Open recorded position in Google Maps" })).toHaveAttribute("href", mapsUrl(driver.current_latitude, driver.current_longitude));
    expect(within(panel).getAllByText(/IST/).length).toBeGreaterThan(0);
  });
  it("does not offer detailed history for off-duty drivers", async () => {
    vi.mocked(listTracking).mockResolvedValue({ ...response, items: [{ ...driver, on_duty: false, can_view_logs: false, stationary_seconds: null }] });
    mount();
    const table = within(await screen.findByRole("table", { name: "Live driver locations" }));
    expect(table.getByRole("button", { name: "Logs" })).toBeDisabled();
    expect(table.getByText("Last known location")).toBeInTheDocument();
    expect(getLocationLogs).not.toHaveBeenCalled();
  });
  it("handles missing GPS without fabricating a map link", async () => {
    vi.mocked(listTracking).mockResolvedValue({ ...response, items: [{ ...driver, current_latitude: null, current_longitude: null, last_location_at: null, location_state: "UNAVAILABLE", stationary_seconds: null }] });
    mount(); const table = within(await screen.findByRole("table", { name: "Live driver locations" }));
    expect(table.getByText("Location unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open Raman/ })).not.toBeInTheDocument();
    expect(table.getByText("Not enough observations")).toBeInTheDocument();
  });
  it("labels stale locations and sends search and false duty filters", async () => {
    vi.mocked(listTracking).mockResolvedValue({ ...response, items: [{ ...driver, location_state: "STALE" }] });
    mount(); const user = userEvent.setup();
    expect(within(await screen.findByRole("table", { name: "Live driver locations" })).getByText("Stale location")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Duty status"), "OFF");
    await waitFor(() => expect(listTracking).toHaveBeenLastCalledWith(expect.objectContaining({ onDuty: false }), expect.anything()));
    await user.type(screen.getByLabelText("Search drivers"), "Raman");
    await waitFor(() => expect(listTracking).toHaveBeenLastCalledWith(expect.objectContaining({ search: "Raman", offset: 0 }), expect.anything()));
  });
  it("hides cached log rows if the driver goes off duty between refreshes", async () => {
    const { client } = mount(); const user = userEvent.setup();
    const table = within(await screen.findByRole("table", { name: "Live driver locations" }));
    await user.click(table.getByRole("button", { name: "Logs" }));
    const panel = await screen.findByRole("dialog");
    await within(panel).findByRole("table", { name: "Driver location history" });
    vi.mocked(getLocationLogs).mockRejectedValue(new AppError({ kind: "conflict", code: "DRIVER_TRACKING_UNAVAILABLE", userMessage: "Driver is now off duty" }));
    await act(async () => { await client.invalidateQueries({ queryKey: ["live-location", "logs"] }); });
    expect(await within(panel).findByText("Driver is now off duty")).toBeInTheDocument();
    expect(within(panel).queryByRole("table", { name: "Driver location history" })).not.toBeInTheDocument();
    expect(within(panel).queryByLabelText("Driver route on OpenStreetMap")).not.toBeInTheDocument();
    expect(within(panel).queryByRole("link", { name: "Open recorded position in Google Maps" })).not.toBeInTheDocument();
  });
  it("renders empty and retryable error states", async () => {
    vi.mocked(listTracking).mockResolvedValue({ ...response, items: [], total: 0 });
    const page = mount();
    expect(await screen.findByText("No matching drivers")).toBeInTheDocument();
    page.unmount();
    vi.mocked(listTracking).mockRejectedValue(new AppError({ kind: "network", userMessage: "Tracking unavailable" }));
    mount();
    expect(await screen.findByText("Tracking unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("tracking formatting", () => {
  it("accepts genuine zero coordinates and rejects unavailable/invalid coordinates", () => {
    expect(mapsUrl(0, 0)).toContain("query=0%2C0");
    expect(mapsUrl(null, 77)).toBeNull();
    expect(mapsUrl(91, 77)).toBeNull();
    expect(mapsUrl(Number.NaN, 77)).toBeNull();
  });
  it("formats stored instants in IST and does not invent missing durations", () => {
    expect(locationTime("2026-10-29T10:05:00Z")).toMatch(/3:35:00 pm IST|15:35:00 IST/i);
    expect(duration(null)).toBe("Not enough observations");
    expect(duration(3661)).toBe("1h 1m");
  });
});
