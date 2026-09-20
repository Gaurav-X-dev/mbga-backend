import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { MESSAGES } from "../api/errors";
import {
  MANAGER_PERMISSIONS,
  createFakeBackend,
  installFakeBackend,
  uninstallFakeBackend,
  type FakeBackend
} from "../test/fake-backend";
import { renderApp } from "../test/render";
import { seedSession } from "../test/session";

const ADMIN_MOBILE = "+919999900001";
const LIMITED_ADMIN_MOBILE = "+919999900021";
const MERCHANT_MOBILE = "+919999900022";
const SLOW = { timeout: 10_000 };

let backend: FakeBackend;

beforeEach(() => {
  backend = createFakeBackend();
  backend.addUser({
    mobile: "+919999900023",
    name: "Ravi Operator",
    status: "ACTIVE",
    channels: { ADMIN: ["dashboard.view"] },
    roles: ["area_supervisor"]
  });
  backend.addUser({
    mobile: LIMITED_ADMIN_MOBILE,
    name: "Limited Admin",
    status: "ACTIVE",
    channels: { ADMIN: ["dashboard.view"] },
    roles: ["support"]
  });
  backend.addUser({
    mobile: MERCHANT_MOBILE,
    name: "Meena Merchant",
    status: "ACTIVE",
    channels: { MERCHANT: MANAGER_PERMISSIONS },
    roles: ["manager"]
  });
  installFakeBackend(backend);
});

afterEach(() => uninstallFakeBackend());

const adminGets = () => backend.calls.filter((call) => call.startsWith("GET /admin/") && !call.includes("/auth/"));

/** Shared checks for the four admin security pages. */
const PAGES = [
  { name: "Users", path: "/admin/users", api: "/admin/users", loading: "Loading users…", empty: "No users yet" },
  { name: "Roles", path: "/admin/roles", api: "/admin/roles", loading: "Loading roles…", empty: "No roles yet" },
  {
    name: "Permissions",
    path: "/admin/permissions",
    api: "/admin/permissions",
    loading: "Loading permissions…",
    empty: "No permissions available"
  },
  {
    name: "Audit logs",
    path: "/admin/audit-logs",
    api: "/admin/audit-logs",
    loading: "Loading audit log entries…",
    empty: "No activity recorded yet"
  }
] as const;

describe.each(PAGES)("$name page states", (page) => {
  it("shows a loading state first", async () => {
    await seedSession("admin", ADMIN_MOBILE);
    backend.options.delayMs = 150;
    renderApp(page.path);
    expect(await screen.findByText(page.loading, {}, SLOW)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(page.loading)).not.toBeInTheDocument(), SLOW);
  });

  it("shows an empty state", async () => {
    await seedSession("admin", ADMIN_MOBILE);
    backend.options.emptyLists = true;
    renderApp(page.path);
    expect(await screen.findByRole("heading", { name: page.empty }, SLOW)).toBeInTheDocument();
  });

  it("shows a safe error with retry when the server fails", async () => {
    await seedSession("admin", ADMIN_MOBILE);
    backend.options.failPaths = [page.api];
    renderApp(page.path);
    expect(await screen.findByText(MESSAGES.server, {}, SLOW)).toBeInTheDocument();
    expect(screen.queryByText(/Traceback/)).not.toBeInTheDocument();
    backend.options.failPaths = [];
    await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.queryByText(MESSAGES.server)).not.toBeInTheDocument(), SLOW);
  }, 20_000);

  it("shows access denied without calling the API when the permission is missing", async () => {
    await seedSession("admin", LIMITED_ADMIN_MOBILE);
    renderApp(page.path);
    expect(await screen.findByRole("heading", { name: "You don’t have access to this page" }, SLOW)).toBeInTheDocument();
    expect(adminGets().filter((call) => call.startsWith(`GET ${page.api}`))).toEqual([]);
  });

  it("is refused to a Merchant session, which never calls Admin APIs", async () => {
    await seedSession("merchant", MERCHANT_MOBILE);
    renderApp(page.path);
    expect(await screen.findByRole("heading", { name: "This area is not part of your panel" }, SLOW)).toBeInTheDocument();
    expect(backend.calls.filter((call) => call.includes(" /admin/"))).toEqual([]);
  });
});

describe("Users page", () => {
  it("lists users in business language", async () => {
    await seedSession("admin", ADMIN_MOBILE);
    renderApp("/admin/users");
    const table = await screen.findByRole("table", {}, SLOW);
    const adminRow = within(table).getByRole("link", { name: "Asha Admin" }).closest("tr") as HTMLElement;
    expect(adminRow).toHaveTextContent("+91 99999 00001");
    expect(adminRow).toHaveTextContent("Super Admin");
    expect(adminRow).toHaveTextContent("Active");
    expect(table).not.toHaveTextContent("super_admin");
  });

  it("asks for confirmation before blocking and only then calls the API", async () => {
    const user = userEvent.setup();
    await seedSession("admin", ADMIN_MOBILE);
    renderApp("/admin/users");
    await screen.findByRole("table", {}, SLOW);

    // The signed-in admin cannot block their own account.
    await user.click(screen.getAllByRole("button", { name: "Actions for Asha Admin" })[0]);
    expect(screen.queryByRole("menuitem", { name: "Block account" })).not.toBeInTheDocument();
    await user.keyboard("{Escape}");

    await user.click(screen.getAllByRole("button", { name: "Actions for Ravi Operator" })[0]);
    await user.click(screen.getByRole("menuitem", { name: "Block account" }));
    let dialog = await screen.findByRole("alertdialog", { name: "Block Ravi Operator?" });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(backend.calls.some((call) => call.endsWith("/block"))).toBe(false);

    await user.click(screen.getAllByRole("button", { name: "Actions for Ravi Operator" })[0]);
    await user.click(screen.getByRole("menuitem", { name: "Block account" }));
    dialog = await screen.findByRole("alertdialog", { name: "Block Ravi Operator?" });
    await user.click(within(dialog).getByRole("button", { name: "Block account" }));

    expect(await screen.findByText("Ravi Operator has been blocked.")).toBeInTheDocument();
    expect(backend.calls.filter((call) => call.startsWith("POST /admin/users/") && call.endsWith("/block"))).toHaveLength(1);
    const row = (within(screen.getByRole("table")).getByRole("link", { name: "Ravi Operator" }).closest("tr")) as HTMLElement;
    await waitFor(() => expect(row).toHaveTextContent("Blocked"));
  });

  it("shows a user's roles and access", async () => {
    const user = userEvent.setup();
    await seedSession("admin", ADMIN_MOBILE);
    renderApp("/admin/users");
    await user.click(within(await screen.findByRole("table", {}, SLOW)).getByRole("link", { name: "Ravi Operator" }));
    expect(await screen.findByRole("heading", { name: /Ravi Operator/, level: 1 })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Roles" }));
    expect((await screen.findAllByRole("link", { name: "Area Supervisor" }))[0]).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Access" }));
    const panel = screen.getByRole("tabpanel");
    // The panel list shows "Admin panel" as a badge (the panel selector also offers it as an option).
    expect((await within(panel).findAllByText("Admin panel", { selector: ".badge" }))[0]).toBeInTheDocument();
    const dashboardGroup = await within(panel).findByRole("heading", { name: "Dashboard" }, SLOW);
    expect(dashboardGroup.closest(".permission-group")).toHaveTextContent("View");
  }, 20_000);
});

describe("Roles page", () => {
  it("lists roles and hides descriptions that only repeat the name", async () => {
    await seedSession("admin", ADMIN_MOBILE);
    renderApp("/admin/roles");
    const table = await screen.findByRole("table", {}, SLOW);
    expect(within(table).getByRole("link", { name: "Area Supervisor" })).toBeInTheDocument();
    expect(table).toHaveTextContent("Oversees merchants in one area");
    expect(table).not.toHaveTextContent("System role:");
    expect(table).toHaveTextContent("Built-in");
    expect(table).toHaveTextContent("Custom");
  });

  it("deactivates a custom role only after confirmation; the Super Admin role cannot be deactivated", async () => {
    const user = userEvent.setup();
    await seedSession("admin", ADMIN_MOBILE);
    renderApp("/admin/roles/role-super");
    expect(await screen.findByRole("heading", { name: "Super Admin", level: 1 }, SLOW)).toBeInTheDocument();
    // Built-in, active and protected: there is no action to offer, so no actions menu is shown.
    expect(screen.queryByRole("button", { name: "More role actions" })).not.toBeInTheDocument();

    await user.click(within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByRole("link", { name: "Roles" }));
    await user.click(within(await screen.findByRole("table")).getByRole("link", { name: "Area Supervisor" }));
    expect(await screen.findByRole("heading", { name: "Area Supervisor", level: 1 })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "More role actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Deactivate role" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Deactivate the Area Supervisor role?" });
    expect(backend.calls.some((call) => call.endsWith("/deactivate"))).toBe(false);
    await user.click(within(dialog).getByRole("button", { name: "Deactivate role" }));
    expect(await screen.findByText("Area Supervisor has been deactivated.")).toBeInTheDocument();
    expect(backend.calls).toContain("POST /admin/roles/role-area/deactivate");
    expect(await screen.findByText("This role is inactive")).toBeInTheDocument();
  }, 20_000);
});

describe("Permissions page", () => {
  it("groups permissions under business names", async () => {
    await seedSession("admin", ADMIN_MOBILE);
    renderApp("/admin/permissions");
    expect(await screen.findByRole("heading", { name: "Merchant management" }, SLOW)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Audit and security" })).toBeInTheDocument();
    expect(screen.getByText("View merchant records")).toBeInTheDocument();
    expect(screen.getByText("Includes sign-in history")).toBeInTheDocument();
    expect(screen.queryByText(/System permission:/)).not.toBeInTheDocument();
    expect(screen.queryByText("merchants.view")).not.toBeInTheDocument();
    expect(screen.getByText("3 permissions available")).toBeInTheDocument();
  });

  it("filters by search text", async () => {
    const user = userEvent.setup();
    await seedSession("admin", ADMIN_MOBILE);
    renderApp("/admin/permissions");
    await screen.findByRole("heading", { name: "Merchant management" }, SLOW);
    await user.type(screen.getByRole("searchbox", { name: "Search permissions" }), "zzz");
    expect(screen.getByRole("heading", { name: "No permissions match your filters" })).toBeInTheDocument();
  });
});

describe("Audit logs page", () => {
  it("shows readable activity and who performed it", async () => {
    await seedSession("admin", ADMIN_MOBILE);
    renderApp("/admin/audit-logs");
    const table = await screen.findByRole("table", {}, SLOW);
    const created = within(table).getByRole("button", { name: "Merchant added" }).closest("tr") as HTMLElement;
    expect(created).toHaveTextContent("Merchants");
    expect(created).toHaveTextContent("You");
    const deactivated = within(table).getByRole("button", { name: "Role deactivated" }).closest("tr") as HTMLElement;
    expect(deactivated).toHaveTextContent("System");
    expect(table).not.toHaveTextContent("merchant.created");
  });

  it("opens the details drawer with a link to the affected record", async () => {
    const user = userEvent.setup();
    await seedSession("admin", ADMIN_MOBILE);
    renderApp("/admin/audit-logs");
    const table = await screen.findByRole("table", {}, SLOW);
    await user.click(within(table).getByRole("button", { name: "Merchant added" }));
    const drawer = await screen.findByRole("dialog", { name: "Merchant added" });
    expect(within(drawer).getByRole("link", { name: "Open the affected record" })).toHaveAttribute(
      "href",
      "/admin/merchants/merchant-x"
    );
    expect(backend.calls).toContain("GET /admin/audit-logs/log-2");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("filters by area and validates the date range", async () => {
    const user = userEvent.setup();
    await seedSession("admin", ADMIN_MOBILE);
    renderApp("/admin/audit-logs");
    await screen.findByRole("table", {}, SLOW);
    await user.selectOptions(screen.getByLabelText("Area"), "role");
    await waitFor(() =>
      expect(within(screen.getByRole("table")).queryByRole("button", { name: "Merchant added" })).not.toBeInTheDocument()
    );
    expect(within(screen.getByRole("table")).getByRole("button", { name: "Role deactivated" })).toBeInTheDocument();

    const callsBefore = backend.calls.length;
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-09-16" } });
    fireEvent.change(screen.getByLabelText(/^To/), { target: { value: "2026-09-10" } });
    expect(await screen.findAllByText("The end date must be on or after the start date.")).not.toHaveLength(0);
    // An impossible range is not sent to the server.
    expect(backend.calls.slice(callsBefore).filter((call) => call.startsWith("GET /admin/audit-logs"))).toHaveLength(0);
  });
});

describe("features without a backend API", () => {
  const MESSAGE = "This feature is not available in the current backend release.";

  it("Admin customer approval shows the message and no data", async () => {
    await seedSession("admin", ADMIN_MOBILE);
    renderApp("/admin/customers");
    expect(await screen.findByText(MESSAGE, {}, SLOW)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(document.querySelector(".stat-card")).toBeNull();
    expect(backend.calls.filter((call) => !call.includes("/auth/"))).toEqual([]);
  });

  it.each(["customers", "orders", "inventory", "payments", "reports"])(
    "Merchant %s shows the message and no data",
    async (page) => {
      await seedSession("merchant", MERCHANT_MOBILE);
      renderApp(`/merchant/${page}`);
      expect(await screen.findByText(MESSAGE, {}, SLOW)).toBeInTheDocument();
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      expect(document.querySelector(".stat-card, svg.chart, canvas")).toBeNull();
      expect(screen.queryByText(/₹|\d+ (orders|cylinders|payments)/i)).not.toBeInTheDocument();
      expect(backend.calls.filter((call) => !call.includes("/auth/"))).toEqual([]);
      const nav = screen.getByRole("navigation", { name: "Main" });
      expect(within(nav).getByRole("link", { name: new RegExp(page, "i") })).toHaveTextContent("Soon");
    }
  );
});
