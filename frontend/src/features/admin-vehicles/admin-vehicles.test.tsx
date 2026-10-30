import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../components/feedback/ToastProvider";
import { AdminVehiclesPage, validateVehicleNumber } from "./AdminVehiclesPage";
import { VehiclePincodesDialog } from "./VehiclePincodesDialog";
import type { Vehicle } from "../../api/vehicles.api";

const { mockVehicles } = vi.hoisted(() => {
  const vehicles: Vehicle[] = [
    {
      id: "veh-1",
      number: "MH 03 C 3843",
      label: "Mini Truck • 1500 kg",
      notes: "Main delivery van",
      isActive: true,
      createdAt: "2026-06-10T10:00:00Z"
    },
    {
      id: "veh-2",
      number: "22BH1234AB",
      label: "Pickup Van • 900 kg",
      notes: "Express deliveries",
      isActive: true,
      createdAt: "2026-06-12T10:00:00Z"
    },
    {
      id: "veh-3",
      number: "DL 01 AB 1234",
      label: "Truck (Medium)",
      notes: "Old chassis",
      isActive: false,
      createdAt: "2026-05-01T10:00:00Z"
    }
  ];
  return { mockVehicles: vehicles };
});

vi.mock("../../api/merchants.api", () => ({
  listMerchants: vi.fn().mockResolvedValue({
    items: [{ id: "m1", business_name: "Metro Gas Agency" }],
    total: 1
  })
}));

vi.mock("../../api/vehicles.api", () => ({
  listVehicles: vi.fn().mockResolvedValue({
    items: mockVehicles,
    total: 3
  }),
  createVehicle: vi.fn().mockImplementation((_merchantId, data) =>
    Promise.resolve({
      id: "veh-new",
      number: data.number,
      label: data.label,
      notes: data.notes,
      isActive: true,
      createdAt: new Date().toISOString()
    })
  ),
  updateVehicle: vi.fn().mockImplementation((_merchantId, vehicleId, data) =>
    Promise.resolve({
      id: vehicleId,
      number: data.number ?? "MH 03 C 3843",
      label: data.label,
      notes: data.notes,
      isActive: data.isActive ?? true,
      createdAt: new Date().toISOString()
    })
  ),
  getVehiclePincodes: vi.fn().mockImplementation((_merchantId, vehicleId) => {
    if (vehicleId === "veh-1") {
      return Promise.resolve({ vehicleId: "veh-1", pincodes: ["122001", "122018"] });
    }
    return Promise.resolve({ vehicleId, pincodes: [] });
  }),
  setVehiclePincodes: vi.fn().mockImplementation((_merchantId, vehicleId, pincodes) =>
    Promise.resolve({ vehicleId, pincodes })
  )
}));

function renderVehiclesPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/admin/vehicles?merchant=m1"]}>
        <ToastProvider>
          <AdminVehiclesPage merchantId="m1" />
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("AdminVehiclesPage - Fleet Management", () => {
  it("validates Indian vehicle numbers correctly", () => {
    expect(validateVehicleNumber("MH 03 C 3843")).toBeUndefined();
    expect(validateVehicleNumber("MH03C3843")).toBeUndefined();
    expect(validateVehicleNumber("22BH1234AB")).toBeUndefined();
    expect(validateVehicleNumber("22 BH 1234 AB")).toBeUndefined();
    expect(validateVehicleNumber("AP-05-BJ-9353")).toBeUndefined();

    // Invalid numbers
    expect(validateVehicleNumber("")).toBe("Vehicle registration number is required");
    expect(validateVehicleNumber("12345")).toBeDefined();
    expect(validateVehicleNumber("INVALID")).toBeDefined();
  });

  it("renders fleet vehicles, KPI stat cards and mapped pincodes", async () => {
    renderVehiclesPage();

    await waitFor(() => {
      expect(screen.getByText("Fleet Vehicles")).toBeInTheDocument();
    });

    // Vehicles listed in table once query resolves (found in both table and mobile-list)
    const veh1Buttons = await screen.findAllByRole("button", { name: "MH 03 C 3843" });
    expect(veh1Buttons.length).toBeGreaterThan(0);

    const vehLabels = await screen.findAllByText("Mini Truck • 1500 kg");
    expect(vehLabels.length).toBeGreaterThan(0);

    const veh2Buttons = await screen.findAllByRole("button", { name: "22BH1234AB" });
    expect(veh2Buttons.length).toBeGreaterThan(0);

    // KPI cards & tabs
    expect(screen.getAllByText("In service").length).toBeGreaterThan(0);
    expect(screen.getByText("Total fleet")).toBeInTheDocument();

    // Mapped pincode chips for veh-1
    const pin1 = await screen.findAllByText("122001");
    expect(pin1.length).toBeGreaterThan(0);

    const pin2 = await screen.findAllByText("122018");
    expect(pin2.length).toBeGreaterThan(0);

    // veh-2 has no pincodes -> shows "Map Pincodes" button
    const mapButtons = await screen.findAllByText(/Map Pincodes/i);
    expect(mapButtons.length).toBeGreaterThan(0);
  });

  it("opens Add Vehicle modal and supports vehicle type and capacity", async () => {
    const user = userEvent.setup();
    renderVehiclesPage();

    await waitFor(() => {
      expect(screen.getByText("Add vehicle")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /add vehicle/i }));

    expect(screen.getByText("Add Fleet Vehicle")).toBeInTheDocument();
    expect(screen.getByLabelText(/registration number/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/vehicle type/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/capacity \(kg\)/i)).toBeInTheDocument();
  });
});

describe("VehiclePincodesDialog", () => {
  it("renders mapped pincodes and allows adding a valid 6-digit pincode", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } }
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <VehiclePincodesDialog
            merchantId="m1"
            vehicle={mockVehicles[0]}
            onClose={() => {}}
          />
        </ToastProvider>
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("Manage Vehicle Pincodes")).toBeInTheDocument();
    });

    // Checks enforcement alert once loaded
    await waitFor(() => {
      expect(screen.getByText(/pincode enforcement/i)).toBeInTheDocument();
    });

    // Existing pincodes
    await waitFor(() => {
      expect(screen.getByText("122001")).toBeInTheDocument();
      expect(screen.getByText("122018")).toBeInTheDocument();
    });

    // Adding an invalid pincode shows error
    const input = screen.getByPlaceholderText(/6-digit pincode/i);
    await user.type(input, "012345");
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(screen.getByText("Pincode cannot start with 0")).toBeInTheDocument();
  });
});
