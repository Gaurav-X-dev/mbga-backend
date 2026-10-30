import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../components/feedback/ToastProvider";
import { AdminOrdersPage } from "./AdminOrdersPage";
import { CreateOrderDialog } from "./CreateOrderDialog";
import { ConfirmOrderDialog, resolveDriverId, findDriver } from "./ConfirmOrderDialog";
import { OrderBulkActionDialog } from "./OrderBulkActionDialog";
import { getCrewConflictMessage } from "./order-utils";
import { OrderDrawer } from "./OrderDrawer";
import type { Order } from "../../api/orders.api";

const { mockOrders } = vi.hoisted(() => {
  const orders: Order[] = [
    {
      id: "ord-1",
      orderNumber: "ORD-2606-0148",
      customerId: "cust-1",
      customerName: "Sharma Enterprises",
      customerType: "RETAIL",
      totalCylinders: 2,
      itemsSummary: "2 × 19 KG",
      orderMode: "NEW",
      source: "MERCHANT_APP",
      deliverySiteName: "Main Office",
      deliveryAddress: { line1: "123 Market Rd", city: "Ahmedabad", state: "Gujarat", pincode: "380001" },
      subtotal: 3600,
      gstPercent: 18,
      gstAmount: 648,
      totalAmount: 4248,
      status: "PLACED",
      canCancel: true,
      placedAt: "2026-06-15T10:30:00Z",
      cutoff: {
        cutoffTime: "18:00",
        withinCutoff: true,
        scheduledDeliveryDate: "2026-06-16",
        message: "Delivery tomorrow",
      },
      items: [
        {
          cylinderType: "LPG_19KG",
          cylinderLabel: "19 KG Commercial",
          quantity: 2,
          unitPrice: 2124,
          lineTotal: 4248,
        },
      ],
      deliveryOtp: "4921",
      invoiceId: "inv-1",
    },
  ];
  return { mockOrders: orders };
});

// Mock API calls
vi.mock("../../api/merchants.api", () => ({
  listMerchants: vi.fn().mockResolvedValue({
    items: [{ id: "m1", business_name: "Test Merchant" }],
    total: 1,
  }),
}));

vi.mock("../../api/orders.api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/orders.api")>();
  return {
    ...actual,
    listOrders: vi.fn().mockResolvedValue(mockOrders),
    listOrderStatuses: vi.fn().mockResolvedValue([
      { code: "PLACED", label: "Awaiting confirmation", tone: "warning" },
      { code: "CONFIRMED", label: "Confirmed", tone: "info" },
    ]),
    getOrderCutoff: vi.fn().mockResolvedValue({
      cutoffTime: "18:00",
      withinCutoff: true,
      scheduledDeliveryDate: "2026-06-16",
      message: "Order within today's cut-off",
    }),
    getOrder: vi.fn().mockResolvedValue(mockOrders[0]),
    listOrderCylinderTypes: vi.fn().mockResolvedValue([
      { code: "LPG_19KG", label: "19 KG Commercial", minimumQuantity: 1, maximumQuantity: 50 },
    ]),
    quoteOrder: vi.fn().mockResolvedValue({
      totalCylinders: 2,
      subtotal: 3600,
      gstPercent: 18,
      gstAmount: 648,
      totalAmount: 4248,
      cutoff: { withinCutoff: true, scheduledDeliveryDate: "2026-06-16", message: "Delivery tomorrow", cutoffTime: "18:00" },
      items: [{ cylinderType: "LPG_19KG", cylinderLabel: "19 KG Commercial", quantity: 2, unitPrice: 2124, lineTotal: 4248 }],
    }),
    createOrder: vi.fn().mockResolvedValue(mockOrders[0]),
  };
});

vi.mock("../../api/customers.api", () => ({
  listCustomers: vi.fn().mockResolvedValue({
    items: [
      {
        id: "cust-1",
        businessName: "Sharma Enterprises",
        customerType: "RETAIL",
        mobile: "9876543210",
        accountStatus: "APPROVED",
        runningBalance: 500,
        deliveryAddress: { line1: "123 Market Rd", city: "Ahmedabad" },
        sites: [],
      },
    ],
  }),
  getCustomerEligibility: vi.fn().mockResolvedValue({
    eligible: true,
    reasons: [],
  }),
}));

vi.mock("../../api/credit.api", () => ({
  getCreditReport: vi.fn().mockResolvedValue({
    items: [
      {
        customerId: "cust-1",
        creditEnabled: true,
        creditLimit: 50000,
        availableCredit: 49500,
      },
    ],
  }),
}));

vi.mock("../../api/vehicles.api", () => ({
  listAvailableVehicles: vi.fn().mockResolvedValue({
    items: [{ id: "v1", number: "GJ01AB1234", label: "Van 1", isActive: true }],
  }),
  listOrderEligibleVehicles: vi.fn().mockResolvedValue([
    { id: "v1", number: "GJ01AB1234", label: "Van 1", isActive: true, matchedPincode: "380001" },
  ]),
}));

vi.mock("../../api/delivery-users.api", () => ({
  listAvailableDeliveryUsers: vi.fn().mockResolvedValue({
    items: [
      { id: "d1", full_name: "Ramesh Patel", mobile_number: "9876543211", delivery_user_type: "DRIVER" },
    ],
  }),
}));

function renderWithClient(ui: React.ReactElement, initialEntries: string[] = ["/?merchant=m1"]) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={initialEntries}>{ui}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

describe("Admin Orders Flow", () => {
  it("renders AdminOrdersPage with status tabs, cylinder filter chips, and KPI metrics", async () => {
    renderWithClient(<AdminOrdersPage merchantId="m1" />);

    const tabs = await screen.findAllByRole("tab");
    expect(tabs.length).toBeGreaterThan(0);

    expect(screen.getByRole("button", { name: "All cylinders" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /19 KG/i })).toBeInTheDocument();

    const customers = await screen.findAllByText("Sharma Enterprises");
    expect(customers.length).toBeGreaterThan(0);

    const orderButtons = screen.getAllByRole("button", { name: "ORD-2606-0148" });
    expect(orderButtons.length).toBeGreaterThan(0);
  });

  it("renders OrderDrawer with OTP confirmation card and delivery details", async () => {
    renderWithClient(
      <OrderDrawer
        merchantId="m1"
        orderId="ord-1"
        onClose={vi.fn()}
        renderStatus={(s) => <span>{s}</span>}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    // Delivery Confirmation OTP card (App parity)
    expect(await screen.findByText("Delivery Confirmation OTP")).toBeInTheDocument();
    expect(screen.getByText("4921")).toBeInTheDocument();

    // Items and Delivery details
    expect(screen.getByText("19 KG Commercial")).toBeInTheDocument();
    expect(screen.getByText("Confirm & Schedule Delivery")).toBeInTheDocument();

    // Tracking Timeline stages
    expect(await screen.findByText("Tracking Timeline")).toBeInTheDocument();
    expect(screen.getByText("Awaiting confirmation")).toBeInTheDocument();
    expect(screen.getByText("Confirmed")).toBeInTheDocument();
  });

  it("renders ConfirmOrderDialog with vehicle, live driver, and date", async () => {
    renderWithClient(
      <ConfirmOrderDialog
        open={true}
        merchantId="m1"
        orders={mockOrders}
        pending={false}
        error={null}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />
    );

    expect(await screen.findByText("Confirm & Schedule Delivery")).toBeInTheDocument();
    expect(screen.getByText("Vehicle")).toBeInTheDocument();
    expect(screen.getByText(/Driver Name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Scheduled Delivery Date/i)).toBeInTheDocument();
  });

  it("renders CreateOrderDialog with customer search, credit display, and mode toggle", async () => {
    const user = userEvent.setup();
    renderWithClient(
      <CreateOrderDialog
        open={true}
        merchantId="m1"
        onClose={vi.fn()}
        onCreated={vi.fn()}
      />
    );

    expect(await screen.findByPlaceholderText(/Search by business name/i)).toBeInTheDocument();

    // Select customer from list
    const customerOption = await screen.findByText("Sharma Enterprises");
    await user.click(customerOption);

    // Verify customer selected and credit row displayed
    expect(await screen.findByText("Eligible to order")).toBeInTheDocument();
    expect(screen.getByText(/Credit:/i)).toBeInTheDocument();

    // Verify New Order vs Repeat Order segmented toggle
    expect(screen.getByRole("tab", { name: /New Order/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Repeat Order/i })).toBeInTheDocument();
  });

  it("correctly resolves driver IDs using user_id over row id and finds driver", () => {
    const member = {
      id: "row-123",
      merchant_id: "m1",
      user_id: "user-456",
      full_name: "Karan Verma",
      mobile_number: "9876543210",
      delivery_user_type: "DRIVER",
      email: null,
      employee_code: "DRV-1",
      driving_license_number: null,
      driving_license_expiry: null,
      address: null,
      status: "ACTIVE",
      approval_status: "APPROVED",
      role: "driver",
      allowed_channel: "DELIVERY",
      created_at: "2026-06-15T10:30:00Z",
    };

    // Prefers user_id for assignment
    expect(resolveDriverId(member)).toBe("user-456");

    // Falls back to id if user_id is missing
    expect(resolveDriverId({ ...member, user_id: "" })).toBe("row-123");

    // findDriver locates driver by either user_id or id
    expect(findDriver([member], "user-456")?.full_name).toBe("Karan Verma");
    expect(findDriver([member], "row-123")?.full_name).toBe("Karan Verma");
  });

  it("handles DELIVERY_USER_NOT_FOUND error safely with a helpful message", () => {
    const err = {
      response: {
        data: {
          detail: {
            code: "DELIVERY_USER_NOT_FOUND",
            message: "We could not find this driver.",
          },
        },
      },
    };

    const msg = getCrewConflictMessage(err, "driver");
    expect(msg).toBe("Selected driver was not found. Please refresh the driver list and select an active driver.");
  });

  it("supports Select All and launches Bulk Action dialog from selection bar", async () => {
    renderWithClient(<AdminOrdersPage merchantId="m1" />);

    // Wait for table to load with orders (rendered in table and mobile list)
    const customers = await screen.findAllByText("Sharma Enterprises");
    expect(customers.length).toBeGreaterThan(0);

    // Select all button in the select bar
    const selectAllBtn = screen.getByRole("checkbox", { name: "Select all" });
    expect(selectAllBtn).toBeInTheDocument();

    // Click select all
    await userEvent.click(selectAllBtn);

    // Deselect all text appears and selection bar is active
    expect(screen.getByText("Deselect all")).toBeInTheDocument();
    expect(screen.getByText(/1 order selected/i)).toBeInTheDocument();

    // Action button for bulk action
    const bulkActionBtns = screen.getAllByRole("button", { name: /bulk action/i });
    expect(bulkActionBtns.length).toBeGreaterThan(0);

    // Click bulk action
    await userEvent.click(bulkActionBtns[0]);

    // OrderBulkActionDialog opens
    expect(await screen.findByRole("heading", { name: /update orders/i, level: 2 })).toBeInTheDocument();
    expect(screen.getByText("Confirm & Schedule")).toBeInTheDocument();
    expect(screen.getByText("Cancel Orders")).toBeInTheDocument();
  });

  it("renders OrderBulkActionDialog with status selector, route assignments, and cancel modes", async () => {
    const handleClose = vi.fn();
    const handleSuccess = vi.fn();

    renderWithClient(
      <OrderBulkActionDialog
        open={true}
        merchantId="m1"
        orders={mockOrders}
        initialAction="CONFIRM"
        onClose={handleClose}
        onSuccess={handleSuccess}
      />
    );

    // Heading with order count and amounts
    expect(await screen.findByRole("heading", { name: /update orders/i, level: 2 })).toBeInTheDocument();

    // Action cards
    const confirmCard = screen.getByText("Confirm & Schedule").closest("button")!;
    const cancelCard = screen.getByText("Cancel Orders").closest("button")!;
    expect(confirmCard).toBeInTheDocument();
    expect(cancelCard).toBeInTheDocument();

    // Route assignments for confirmation
    expect(screen.getByText("Delivery vehicle")).toBeInTheDocument();
    expect(screen.getByText("Assigned driver")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /confirm & schedule 1 order/i })).toBeInTheDocument();

    // Switch to Cancel mode
    await userEvent.click(cancelCard);
    expect(await screen.findByLabelText(/cancellation reason/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cancel 1 order/i })).toBeInTheDocument();
  });
});

