import { screen, waitFor, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { tokenStorage } from "./auth/token-storage";
import { createFakeBackend, installFakeBackend, uninstallFakeBackend, type FakeBackend } from "./test/fake-backend";
import { renderApp } from "./test/render";

async function enterOtp(user: UserEvent, code: string) {
  const first = await screen.findByLabelText("Digit 1 of 4");
  await user.click(first);
  await user.keyboard(code);
}

async function signIn(user: UserEvent, panel: "Admin panel" | "Merchant panel", localMobile: string, code = "1234") {
  await screen.findByRole("heading", { name: "Welcome to MBGA" });
  await user.click(screen.getByRole("radio", { name: panel }));
  await user.type(screen.getByLabelText(/Mobile number/), localMobile);
  await user.click(screen.getByRole("button", { name: "Send verification code" }));
  await enterOtp(user, code);
}

async function signOut(user: UserEvent) {
  await user.click(screen.getByRole("button", { name: /Open account menu/ }));
  await user.click(await screen.findByRole("menuitem", { name: "Sign out" }));
  await screen.findByRole("heading", { name: "Welcome to MBGA" });
}

describe("sign in", () => {
  let backend: FakeBackend;
  beforeEach(() => {
    backend = createFakeBackend();
    installFakeBackend(backend);
  });
  afterEach(() => uninstallFakeBackend());

  it("shows the mobile step with MBGA branding and no prefilled credentials", async () => {
    renderApp("/login");
    expect(await screen.findByRole("heading", { name: "Welcome to MBGA" })).toBeInTheDocument();
    expect(screen.getByText("Sign in to manage your MBGA operations.")).toBeInTheDocument();
    expect(screen.getByLabelText(/Mobile number/)).toHaveValue("");
    expect(screen.queryByText(/1234/)).not.toBeInTheDocument();
  });

  it("validates the mobile number before contacting the server", async () => {
    const user = userEvent.setup();
    renderApp("/login");
    await screen.findByRole("heading", { name: "Welcome to MBGA" });
    await user.click(screen.getByRole("button", { name: "Send verification code" }));
    expect(await screen.findByText("Enter a mobile number.")).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Mobile number/), "12345");
    await user.click(screen.getByRole("button", { name: "Send verification code" }));
    expect(await screen.findByText("Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9.")).toBeInTheDocument();
    expect(screen.getByLabelText(/Mobile number/)).toHaveAttribute("aria-invalid", "true");
    expect(backend.calls).toHaveLength(0);
  });

  it("does not reveal whether a number is registered", async () => {
    const user = userEvent.setup();
    renderApp("/login");
    await screen.findByRole("heading", { name: "Welcome to MBGA" });
    await user.type(screen.getByLabelText(/Mobile number/), "9999999999");
    await user.click(screen.getByRole("button", { name: "Send verification code" }));
    const group = await screen.findByRole("group", { name: "Verification code" });
    expect(screen.getByText(/has access to the/)).toBeInTheDocument();
    await user.click(within(group).getAllByRole("textbox")[0]);
    await user.paste("1234");
    expect(await screen.findByRole("alert")).toHaveTextContent("The verification code is incorrect. Please try again.");
    expect(screen.queryByRole("heading", { name: "Dashboard" })).not.toBeInTheDocument();
  });

  it("uses exactly four boxes, masks the number and supports paste", async () => {
    const user = userEvent.setup();
    renderApp("/login");
    await screen.findByRole("heading", { name: "Welcome to MBGA" });
    await user.type(screen.getByLabelText(/Mobile number/), "9999900001");
    await user.click(screen.getByRole("button", { name: "Send verification code" }));
    const group = await screen.findByRole("group", { name: "Verification code" });
    expect(within(group).getAllByRole("textbox")).toHaveLength(4);
    expect(screen.getByText("+91 ••••• ••001")).toBeInTheDocument();
    expect(screen.getByText(/Resend code in 0:3\d|Resend code in 0:29/)).toBeInTheDocument();
    await user.click(within(group).getAllByRole("textbox")[0]);
    await user.paste("1234");
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(backend.calls).toContain("POST /admin/auth/otp/verify");
  });

  it("shows a friendly message for a wrong code and lets the user retry", async () => {
    const user = userEvent.setup();
    renderApp("/login");
    await signIn(user, "Admin panel", "9999900001", "9999");
    expect(await screen.findByRole("alert")).toHaveTextContent("The verification code is incorrect. Please try again.");
    expect(screen.getByLabelText("Digit 1 of 4")).toHaveValue("");
    await enterOtp(user, "1234");
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("asks for a new code when the code has expired", async () => {
    const user = userEvent.setup();
    renderApp("/login");
    await screen.findByRole("heading", { name: "Welcome to MBGA" });
    await user.type(screen.getByLabelText(/Mobile number/), "9999900001");
    await user.click(screen.getByRole("button", { name: "Send verification code" }));
    await screen.findByLabelText("Digit 1 of 4");
    backend.expireChallenges();
    await enterOtp(user, "1234");
    expect(await screen.findByRole("alert")).toHaveTextContent("This verification code has expired. Request a new code.");
    await user.click(screen.getByRole("button", { name: "Request a new code" }));
    expect(await screen.findByText("We sent a new verification code.")).toBeInTheDocument();
    await enterOtp(user, "1234");
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("tells an Admin who picked the Merchant panel that they have no access there", async () => {
    const user = userEvent.setup();
    renderApp("/login");
    await signIn(user, "Merchant panel", "9999900001");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your account does not have access to this panel. Check that you selected the correct account type."
    );
    expect(tokenStorage.get()).toBeNull();
  });

  it("lets the user change the mobile number", async () => {
    const user = userEvent.setup();
    renderApp("/login");
    await screen.findByRole("heading", { name: "Welcome to MBGA" });
    await user.type(screen.getByLabelText(/Mobile number/), "9999900001");
    await user.click(screen.getByRole("button", { name: "Send verification code" }));
    await user.click(await screen.findByRole("button", { name: "Change mobile number" }));
    expect(screen.getByLabelText(/Mobile number/)).toHaveValue("9999900001");
  });

  it("returns to the page the user originally asked for", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/admin/merchants");
    await signIn(user, "Admin panel", "9999900001");
    expect(await screen.findByRole("heading", { name: "Merchants", level: 1 })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/admin/merchants");
  });

  it("signs out and clears only the app session", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem("unrelated", "keep-me");
    renderApp("/login");
    await signIn(user, "Admin panel", "9999900001");
    await screen.findByRole("heading", { name: "Dashboard" });
    expect(tokenStorage.get()?.channel).toBe("admin");
    await signOut(user);
    expect(await screen.findByText("You have signed out.")).toBeInTheDocument();
    expect(tokenStorage.get()).toBeNull();
    expect(window.localStorage.getItem("unrelated")).toBe("keep-me");
    expect(backend.calls).toContain("POST /admin/auth/logout");
  });

  it("signs out from all devices after confirmation", async () => {
    const user = userEvent.setup();
    renderApp("/login");
    await signIn(user, "Admin panel", "9999900001");
    await screen.findByRole("heading", { name: "Dashboard" });
    await user.click(screen.getByRole("button", { name: /Open account menu/ }));
    await user.click(await screen.findByRole("menuitem", { name: "Sign out from all devices" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Sign out from all devices?" });
    await user.click(within(dialog).getByRole("button", { name: "Sign out everywhere" }));
    await screen.findByRole("heading", { name: "Welcome to MBGA" });
    expect(backend.calls).toContain("POST /admin/auth/logout-all");
    expect(tokenStorage.get()).toBeNull();
  });
});

describe("core flow: Admin adds a merchant, merchant builds a delivery team", () => {
  let backend: FakeBackend;
  beforeEach(() => {
    backend = createFakeBackend();
    installFakeBackend(backend);
  });
  afterEach(() => uninstallFakeBackend());

  it("completes the whole journey through the UI", async () => {
    const user = userEvent.setup();
    renderApp("/login");

    // Admin signs in and adds a merchant.
    await signIn(user, "Admin panel", "9999900001");
    await screen.findByRole("heading", { name: "Dashboard" });
    await user.click(within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: /Merchants/ }));
    expect(await screen.findByRole("heading", { name: "No merchants yet" })).toBeInTheDocument();
    await user.click(screen.getAllByRole("link", { name: "Add merchant" })[0]);
    await screen.findByRole("heading", { name: "Add merchant" });

    // Validation first.
    await user.click(screen.getByRole("button", { name: "Continue to review" }));
    expect(await screen.findByText("Enter the business name.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Please check the highlighted information.");

    await user.type(screen.getByLabelText(/Business name/), "Sharma Gas Agency");
    await user.type(screen.getByLabelText(/Merchant code/), "sharma-gas-01");
    await user.type(screen.getByLabelText(/Contact person name/), "Rakesh Sharma");
    await user.type(screen.getByLabelText(/^Mobile number/), "9111111111");
    await user.type(screen.getByLabelText(/^City/), "Kanpur");
    await user.click(screen.getByRole("button", { name: "Continue to review" }));
    expect(await screen.findByRole("heading", { name: "Review and create" })).toBeInTheDocument();
    expect(screen.getByText("SHARMA-GAS-01")).toBeInTheDocument();
    expect(screen.getByText("+91 91111 11111")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create merchant" }));

    expect(await screen.findByRole("heading", { name: "Sharma Gas Agency is ready to use MBGA" })).toBeInTheDocument();
    expect(backend.merchants[0]).toMatchObject({
      merchant_code: "SHARMA-GAS-01",
      mobile_number: "+919111111111",
      city: "Kanpur"
    });

    // The list reflects the new merchant without a page reload.
    await user.click(screen.getByRole("link", { name: "Back to merchants" }));
    // Tables also render a compact card list for small screens (hidden by CSS on desktop).
    expect((await screen.findAllByRole("link", { name: "Sharma Gas Agency" }))[0]).toBeInTheDocument();

    // A duplicate code is reported on the field.
    await user.click(screen.getAllByRole("link", { name: "Add merchant" })[0]);
    await user.type(await screen.findByLabelText(/Business name/), "Another Agency");
    await user.type(screen.getByLabelText(/Merchant code/), "SHARMA-GAS-01");
    await user.type(screen.getByLabelText(/Contact person name/), "Other Person");
    await user.type(screen.getByLabelText(/^Mobile number/), "9222222222");
    await user.click(screen.getByRole("button", { name: "Continue to review" }));
    await user.click(await screen.findByRole("button", { name: "Create merchant" }));
    expect(await screen.findByText("This merchant code is already in use. Choose a different code.", { selector: ".field__error span" })).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Cancel" }));
    const leave = await screen.findByRole("alertdialog", { name: "Leave without saving?" });
    await user.click(within(leave).getByRole("button", { name: "Leave page" }));
    await screen.findByRole("heading", { name: "Merchants", level: 1 });

    await signOut(user);

    // The merchant signs in and adds a driver and a helper.
    await signIn(user, "Merchant panel", "9111111111");
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).queryByRole("link", { name: /Users/ })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: /^Merchants/ })).not.toBeInTheDocument();
    await user.click(within(nav).getByRole("link", { name: /Delivery team/ }));
    // Wait until the list has loaded before using its actions.
    await screen.findByRole("heading", { name: "No team members yet" });
    const addTeamMemberLink = screen
      .getAllByRole("link", { name: "Add team member" })
      .find((link) => link.getAttribute("href") === "/merchant/delivery-team/new");
    expect(addTeamMemberLink).toBeDefined();
    await user.click(addTeamMemberLink as HTMLElement);
    await screen.findByRole("heading", { name: "Add team member" });

    await user.click(screen.getByRole("radio", { name: /Driver/ }));
    await user.type(screen.getByLabelText(/Full name/), "Suresh Kumar");
    await user.type(screen.getByLabelText(/^Mobile number/), "9333333333");
    await user.type(screen.getByLabelText(/Employee code/), "DRV-001");
    await user.click(screen.getByRole("button", { name: "Add team member" }));
    expect(await screen.findByText("Enter the driving licence number.", { selector: ".field__error span" })).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Driving licence number/), "DL-0420110012345");
    await user.type(screen.getByLabelText(/Licence expiry date/), "2031-12-31");
    await user.click(screen.getByRole("button", { name: "Add team member" }));
    expect(await screen.findByRole("heading", { name: "Suresh Kumar has joined your delivery team" })).toBeInTheDocument();
    expect(screen.getByText(/open the MBGA Delivery app and sign in/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add another team member" }));
    await user.click(await screen.findByRole("radio", { name: /Helper/ }));
    expect(screen.queryByLabelText(/Driving licence number/)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText(/Full name/), "Ramesh Yadav");
    await user.type(screen.getByLabelText(/^Mobile number/), "9444444444");
    await user.type(screen.getByLabelText(/Employee code/), "HLP-001");
    await user.click(screen.getByRole("button", { name: "Add team member" }));
    expect(await screen.findByRole("heading", { name: "Ramesh Yadav has joined your delivery team" })).toBeInTheDocument();
    expect(backend.deliveryMembers.map((member) => member.delivery_user_type)).toEqual(["HELPER", "DRIVER"]);

    // List and detail reflect the new members.
    await user.click(screen.getByRole("link", { name: "Back to delivery team" }));
    expect((await screen.findAllByRole("link", { name: "Suresh Kumar" }))[0]).toBeInTheDocument();
    await user.click(screen.getAllByRole("link", { name: "Ramesh Yadav" })[0]);
    expect(await screen.findByRole("heading", { name: /Ramesh Yadav/, level: 1 })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Driving licence" })).not.toBeInTheDocument();

    await signOut(user);
    await waitFor(() => expect(tokenStorage.get()).toBeNull());
    expect(backend.calls).toContain("POST /merchant/auth/logout");
  }, 60000);

  it("shows permission denied from the server as a friendly message", async () => {
    const user = userEvent.setup();
    renderApp("/login");
    await signIn(user, "Admin panel", "9999900001");
    await screen.findByRole("heading", { name: "Dashboard" });
    backend.options.forbidAll = true;
    await user.click(within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: /Merchants/ }));
    expect(await screen.findByText("You don’t have access to this")).toBeInTheDocument();
    expect(screen.getByText("You don’t have permission to perform this action.")).toBeInTheDocument();
  });
});
