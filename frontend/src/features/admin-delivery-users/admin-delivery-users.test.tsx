import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../components/feedback/ToastProvider";
import { AdminDeliveryUsersPage } from "./AdminDeliveryUsersPage";
import type { AdminDeliveryUser } from "../../api/delivery-users.api";

const { mockDeliveryUsers } = vi.hoisted(() => {
  const users: AdminDeliveryUser[] = [
    {
      id: "du-1",
      user_id: "usr-1",
      merchant_id: "m1",
      full_name: "Ramesh Driver",
      email: "ramesh@example.com",
      mobile_number: "+919876543210",
      delivery_user_type: "DRIVER",
      role: "DRIVER",
      address: "123 Market Rd",
      employee_code: "EMP-01",
      driving_license_number: "DL1420110012345",
      driving_license_expiry: "2028-12-31",
      status: "ACTIVE",
      approval_status: "APPROVED",
      on_duty: true,
      allowed_channel: "DELIVERY",
      created_at: "2026-01-10T10:00:00Z",
    },
    {
      id: "du-2",
      user_id: "usr-2",
      merchant_id: "m1",
      full_name: "Suresh Driver",
      email: "suresh@example.com",
      mobile_number: "+919876543211",
      delivery_user_type: "DRIVER",
      role: "DRIVER",
      address: "456 Station Rd",
      employee_code: "EMP-02",
      driving_license_number: "DL1420110099999",
      driving_license_expiry: "2026-11-01",
      status: "PENDING_APPROVAL",
      approval_status: "PENDING",
      on_duty: false,
      allowed_channel: "DELIVERY",
      created_at: "2026-02-15T10:00:00Z",
    },
  ];
  return { mockDeliveryUsers: users };
});

vi.mock("../../auth/auth-context", () => ({
  useAuth: () => ({
    user: { id: "admin-1", email: "admin@mbga.test", role: "SUPER_ADMIN" },
    can: () => true,
    channel: "admin",
  }),
}));

vi.mock("../../api/merchants.api", () => ({
  listMerchants: vi.fn().mockResolvedValue({
    items: [{ id: "m1", business_name: "Metro Gas Agency" }],
    total: 1,
  }),
}));

vi.mock("../../api/delivery-users.api", () => ({
  listDeliveryUsers: vi.fn().mockResolvedValue({
    items: mockDeliveryUsers,
    total: 2,
  }),
  listAvailableDeliveryUsers: vi.fn().mockResolvedValue({
    items: [mockDeliveryUsers[0]],
    total: 1,
  }),
  getDeliveryUser: vi.fn().mockImplementation((_merchantId, id) => {
    const found = mockDeliveryUsers.find((u) => u.id === id);
    return Promise.resolve(found ?? mockDeliveryUsers[0]);
  }),
  createDeliveryUser: vi.fn().mockImplementation((_merchantId, data) =>
    Promise.resolve({
      ...mockDeliveryUsers[0],
      id: "du-new",
      full_name: data.full_name,
      mobile_number: data.mobile_number,
      delivery_user_type: "DRIVER",
    })
  ),
  updateDeliveryUser: vi.fn().mockImplementation((_merchantId, _id, data) =>
    Promise.resolve({
      ...mockDeliveryUsers[0],
      ...data,
    })
  ),
  changeDeliveryUserStatus: vi.fn().mockResolvedValue(mockDeliveryUsers[0]),
}));

function LocationWatcher({ onLocation }: { onLocation: (search: string) => void }) {
  const loc = useLocation();
  onLocation(loc.search);
  return null;
}

function renderDeliveryUsers(initialEntry = "/admin/delivery-users?merchant=m1&type=HELPER") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  let currentSearch = "";

  const utils = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <ToastProvider>
          <LocationWatcher onLocation={(search) => { currentSearch = search; }} />
          <AdminDeliveryUsersPage />
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );

  return { ...utils, getCurrentSearch: () => currentSearch };
}

describe("Admin Delivery Users Page", () => {
  it("normalizes away type=HELPER and displays driver-only UI and KPIs", async () => {
    const { getCurrentSearch } = renderDeliveryUsers("/admin/delivery-users?merchant=m1&type=HELPER");

    // Page title
    expect(await screen.findByRole("heading", { name: "Delivery drivers", level: 1 })).toBeInTheDocument();

    // Verify type=HELPER is stripped from the URL
    await waitFor(() => {
      expect(getCurrentSearch()).not.toContain("type=HELPER");
    });

    // KPI cards: Drivers and Available now, NO Helpers card
    expect(screen.getByText("Drivers")).toBeInTheDocument();
    expect(screen.getByText("Available now")).toBeInTheDocument();
    expect(screen.queryByText("Helpers")).not.toBeInTheDocument();

    // Tabs: All Drivers, Active, Pending approval, Blocked (NO Helpers tab)
    expect(screen.getByRole("tab", { name: "All Drivers" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Active" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Pending approval" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Blocked" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /helper/i })).not.toBeInTheDocument();

    // Table contains drivers (rendered in both desktop table and mobile list)
    const rameshButtons = await screen.findAllByRole("button", { name: "Ramesh Driver" });
    expect(rameshButtons.length).toBeGreaterThan(0);

    const sureshButtons = await screen.findAllByRole("button", { name: "Suresh Driver" });
    expect(sureshButtons.length).toBeGreaterThan(0);
  });

  it("opens Add Driver dialog configured only for drivers", async () => {
    renderDeliveryUsers("/admin/delivery-users?merchant=m1");

    const addBtn = await screen.findByRole("button", { name: "Add driver" });
    await userEvent.click(addBtn);

    // Modal opens with Add driver title
    expect(await screen.findByRole("heading", { name: "Add driver", level: 2 })).toBeInTheDocument();

    // Does not present helper role option
    expect(screen.queryByLabelText(/helper/i)).not.toBeInTheDocument();
  });
});
