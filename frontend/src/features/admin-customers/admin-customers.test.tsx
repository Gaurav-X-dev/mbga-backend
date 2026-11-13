import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { AddCustomerDialog } from "./AddCustomerDialog";
import * as customersApi from "../../api/customers.api";
import * as locationsApi from "../../api/locations.api";

vi.mock("../../api/customers.api", async (importOriginal) => {
  const actual = await importOriginal<typeof customersApi>();
  return {
    ...actual,
    getCustomerKycRequirements: vi.fn(),
    createCustomer: vi.fn(),
    uploadDocument: vi.fn()
  };
});

vi.mock("../../api/locations.api", async (importOriginal) => {
  const actual = await importOriginal<typeof locationsApi>();
  return {
    ...actual,
    lookupPincode: vi.fn()
  };
});

describe("AddCustomerDialog (3-Step Registration Wizard)", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false }
      }
    });

    vi.mocked(customersApi.getCustomerKycRequirements).mockImplementation(async type=>({customerType:type,minimumDocuments:type==="INDUSTRIAL"?2:1,requiresDeliverySites:type==="INDUSTRIAL",documents:(type==="INDUSTRIAL"?["GST","PAN"]:["AADHAAR"]).map(code=>({type:code,label:code,required:true,numberFormat:"Valid registration number"}))}));
    vi.mocked(locationsApi.lookupPincode).mockResolvedValue({
      pincode: "122018",
      serviceable: true,
      district: "Gurgaon",
      state: "Haryana",
      offices: [{ officeName: "Sector 14", officeType: "Sub Post Office", deliveryAvailable: true }]
    });

    vi.mocked(customersApi.uploadDocument).mockResolvedValue({
      fileId: "doc-file-123",
      fileName: "aadhaar.pdf",
      contentType: "application/pdf",
      size: 102400
    });

    vi.mocked(customersApi.createCustomer).mockResolvedValue({
      id: "cust-new-1",
      code: "CUST-001",
      customerType: "RETAIL",
      businessName: "Sharma General Store",
      ownerName: "Ramesh Sharma",
      mobile: "9876543210",
      email: "ramesh@sharma.com",
      accountStatus: "PENDING_APPROVAL",
      kycStatus: "PENDING",
      pricingTier: "STANDARD",
      deliveryAddress: {
        line1: "Shop 12, Main Market",
        line2: "Sector 14",
        city: "Gurgaon",
        state: "Haryana",
        pincode: "122018"
      },
      runningBalance: 0
    });
  });

  const renderDialog = (props?: Partial<Parameters<typeof AddCustomerDialog>[0]>) => {
    const onClose = vi.fn();
    const onCreated = vi.fn();
    const result = render(
      <QueryClientProvider client={queryClient}>
        <AddCustomerDialog
          open={true}
          merchantId="merch-1"
          onClose={onClose}
          onCreated={onCreated}
          {...props}
        />
      </QueryClientProvider>
    );
    return { ...result, onClose, onCreated };
  };

  it("renders Step 0: Customer Type with Retail and Industrial cards", () => {
    renderDialog();
    expect(screen.getByRole("heading", { name: /select customer type/i })).toBeInTheDocument();
    expect(screen.getByText("Retail Customer")).toBeInTheDocument();
    expect(screen.getByText("Industrial Customer")).toBeInTheDocument();
    expect(screen.getByText(/5, 10 & 19 KG cylinders/i)).toBeInTheDocument();
    expect(screen.getByText(/47.5 KG & 422 KG Hippo/i)).toBeInTheDocument();
  });

  it("navigates from Step 0 to Step 1 and validates required business details", async () => {
    const user = userEvent.setup();
    renderDialog();

    // Click Continue to go to Step 1
    const continueBtn = screen.getByRole("button", { name: /continue/i });
    await user.click(continueBtn);

    // Now on Step 1: Customer Details
    expect(screen.getByRole("heading", { name: /customer details/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/business \/ shop name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/contact person name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/customer mobile number/i)).toBeInTheDocument();

    // Clicking continue without filling fields triggers validation
    await user.click(screen.getByRole("button", { name: /continue/i }));
    expect(screen.getByText(/business \/ shop name is required/i)).toBeInTheDocument();
    expect(screen.getByText(/contact person name is required/i)).toBeInTheDocument();
    expect(screen.getByText(/customer mobile number is required/i)).toBeInTheDocument();
  });

  it("supports going Back to previous step", async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("button", { name: /continue/i }));
    expect(screen.getByRole("heading", { name: /customer details/i })).toBeInTheDocument();

    const backBtn = screen.getByRole("button", { name: /back/i });
    await user.click(backBtn);
    expect(screen.getByRole("heading", { name: /select customer type/i })).toBeInTheDocument();
  });

  it("fills Step 1 and navigates to Step 2: KYC Documents", async () => {
    const user = userEvent.setup();
    renderDialog();

    // Step 0 -> Step 1
    await user.click(screen.getByRole("button", { name: /continue/i }));

    // Fill Step 1 details
    await user.type(screen.getByLabelText(/business \/ shop name/i), "Sharma General Store");
    await user.type(screen.getByLabelText(/contact person name/i), "Ramesh Sharma");
    await user.type(screen.getByLabelText(/customer mobile number/i), "9876543210");
    await user.type(screen.getByLabelText(/delivery pincode/i), "122018");

    // Wait for pincode lookup
    await waitFor(() => {
      expect(locationsApi.lookupPincode).toHaveBeenCalledWith("122018", "merch-1", expect.anything(), "admin");
    });

    await user.type(screen.getByLabelText(/delivery address line 1/i), "Shop 12, Main Market");

    // Proceed to Step 2
    await user.click(screen.getByRole("button", { name: /continue/i }));

    // Now on Step 2: KYC Documents
    expect(screen.getByRole("heading", { name: /kyc documents/i })).toBeInTheDocument();
    expect(screen.getByText("Aadhaar Card")).toBeInTheDocument();
    expect(screen.getByLabelText(/aadhaar card number/i)).toBeInTheDocument();
  });

  it("validates document number and file on Step 2 before opening confirmation modal", async () => {
    const user = userEvent.setup();
    const { onCreated } = renderDialog();

    // Advance to Step 1
    await user.click(screen.getByRole("button", { name: /continue/i }));

    // Fill Step 1
    await user.type(screen.getByLabelText(/business \/ shop name/i), "Sharma General Store");
    await user.type(screen.getByLabelText(/contact person name/i), "Ramesh Sharma");
    await user.type(screen.getByLabelText(/customer mobile number/i), "9876543210");
    await user.type(screen.getByLabelText(/delivery pincode/i), "122018");
    await user.type(screen.getByLabelText(/delivery address line 1/i), "Shop 12, Main Market");

    // Advance to Step 2
    await user.click(screen.getByRole("button", { name: /continue/i }));

    // Click Review & Register without doc number or file
    const reviewBtn = screen.getByRole("button", { name: /review & register/i });
    await user.click(reviewBtn);

    expect(screen.getByText(/aadhaar card number is required/i)).toBeInTheDocument();

    // Type valid 12-digit Aadhaar number
    await user.type(screen.getByLabelText(/aadhaar card number/i), "123456789012");

    // Upload mock file
    const file = new File(["dummy pdf content"], "aadhaar.pdf", { type: "application/pdf" });
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).toBeTruthy();
    await user.upload(fileInput, file);

    expect(screen.getByText("aadhaar.pdf")).toBeInTheDocument();
    expect(screen.getByText(/attached/i)).toBeInTheDocument();

    // Now click Review & Register
    await user.click(reviewBtn);

    // Confirmation modal should open with summary details
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /register this customer\?/i })).toBeInTheDocument();
    });
    expect(screen.getByText("Sharma General Store")).toBeInTheDocument();
    expect(screen.getByText("Ramesh Sharma")).toBeInTheDocument();
    expect(screen.getByText("+91 98765 43210")).toBeInTheDocument();

    // Click Confirm & Register
    const confirmBtn = screen.getByRole("button", { name: /confirm & register customer/i });
    await user.click(confirmBtn);

    await waitFor(() => {
      expect(customersApi.uploadDocument).toHaveBeenCalledWith("merch-1", expect.any(File), "AADHAAR");
      expect(customersApi.createCustomer).toHaveBeenCalledWith(
        "merch-1",
        expect.objectContaining({
          customerType: "RETAIL",
          businessName: "Sharma General Store",
          ownerName: "Ramesh Sharma",
          mobile: "9876543210"
        })
      );
      expect(onCreated).toHaveBeenCalled();
    });
  });

  it("configures Industrial customer with multi-site and commercial KYC documents", async () => {
    const user = userEvent.setup();
    renderDialog();

    // Select Industrial Customer on Step 0
    const industrialCard = screen.getByText("Industrial Customer").closest(".customer-type-card")!;
    await user.click(industrialCard);
    expect(industrialCard).toHaveClass("is-selected");

    // Move to Step 1
    await user.click(screen.getByRole("button", { name: /continue/i }));

    // Verify delivery sites section is displayed for Industrial customers
    expect(screen.getByText("Additional Delivery Sites")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add site/i })).toBeInTheDocument();

    // Fill Step 1 details
    await user.type(screen.getByLabelText(/business \/ shop name/i), "Apex Manufacturing Ltd");
    await user.type(screen.getByLabelText(/contact person name/i), "Vikram Patel");
    await user.type(screen.getByLabelText(/customer mobile number/i), "9823456789");
    await user.type(screen.getByLabelText(/delivery pincode/i), "122018");
    await user.type(screen.getByLabelText(/delivery address line 1/i), "Plot 45, Industrial Zone");

    // Move to Step 2
    await user.click(screen.getByRole("button", { name: /continue/i }));

    // Verify Industrial KYC follows the returned GST/PAN requirements
    expect(screen.getByText("PAN Card")).toBeInTheDocument();
    expect(screen.getByText("GST Certificate")).toBeInTheDocument();
  });
});
