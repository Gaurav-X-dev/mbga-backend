import { expect, test, type Page, type TestInfo } from "@playwright/test";

import { E2E, E2E_RECORDS, expectNoTechnicalText, formatMobile, signIn, signOut } from "./helpers";

/**
 * Real browser + real backend (http://127.0.0.1:8005) journey with fixed, repeatable test data:
 * Super Admin signs in → dashboard → merchants → adds a merchant → signs out →
 * merchant signs in → dashboard → adds a driver and a helper → delivery team list → signs out.
 * Records are removed before and after the run by e2e/global-setup.ts / global-teardown.ts.
 */

type ApiCall = { step: string; method: string; path: string; status: number };

function recordApiCalls(page: Page) {
  const calls: ApiCall[] = [];
  let current = "start";
  page.on("response", (response) => {
    const url = response.url();
    if (!url.includes("/api/v1/") || response.request().method() === "OPTIONS") return;
    calls.push({
      step: current,
      method: response.request().method(),
      path: new URL(url).pathname.replace("/api/v1", "") + new URL(url).search,
      status: response.status()
    });
  });
  return {
    calls,
    async step(name: string, body: () => Promise<void>) {
      current = name;
      await test.step(name, body);
      await expectNoTechnicalText(page);
    }
  };
}

async function report(testInfo: TestInfo, calls: ApiCall[]) {
  const lines = calls.map((call) => `${call.step} | ${call.method} ${call.path} | ${call.status}`);
  console.log(["API calls per step:", ...lines].join("\n"));
  await testInfo.attach("api-calls.json", { body: JSON.stringify(calls, null, 2), contentType: "application/json" });
}

test("super admin adds a merchant who then builds a delivery team", async ({ page }, testInfo) => {
  const { merchant, driver, helper } = E2E_RECORDS;
  const api = recordApiCalls(page);

  await api.step("1. Super Admin sign in", async () => {
    await page.goto("/login");
    await signIn(page, "Admin panel", E2E.adminMobile);
    await expect(page).toHaveURL(/\/admin\/dashboard$/);
  });

  await api.step("2. Admin dashboard", async () => {
    await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
    await expect(page.getByText("Total merchants")).toBeVisible();
    await expect(page.locator(".skeleton")).toHaveCount(0);
  });

  await api.step("3. Merchant list", async () => {
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Merchants" }).click();
    await expect(page.getByRole("heading", { name: "Merchants", level: 1 })).toBeVisible();
    await expect(page.getByRole("table")).toBeVisible();
    await expect(page.getByRole("table").getByRole("link", { name: merchant.businessName })).toHaveCount(0);
  });

  await api.step("4. Create test merchant", async () => {
    await page.getByRole("link", { name: "Add merchant" }).first().click();
    await expect(page.getByRole("heading", { name: "Add merchant", level: 1 })).toBeVisible();
    await page.getByRole("button", { name: "Continue to review" }).click();
    await expect(page.getByText("Enter the business name.").first()).toBeVisible();

    await page.getByLabel("Business name").fill(merchant.businessName);
    await page.getByLabel("Merchant code").fill(merchant.code);
    await page.getByLabel("Contact person name").fill(merchant.contactName);
    await page.getByLabel("Mobile number").fill(merchant.mobile);
    await page.getByLabel("Email address").fill(merchant.email);
    await page.getByLabel("City").fill("Kanpur");
    await page.getByLabel("State").fill("Uttar Pradesh");
    await page.getByRole("button", { name: "Continue to review" }).click();
    await expect(page.getByRole("heading", { name: "Review and create" })).toBeVisible();
    await page.getByRole("button", { name: "Create merchant" }).click();

    await expect(page.getByRole("heading", { name: `${merchant.businessName} is ready to use MBGA` })).toBeVisible();
    await page.getByRole("link", { name: "Back to merchants" }).click();
    await expect(page.getByRole("table").getByRole("link", { name: merchant.businessName })).toBeVisible();
  });

  await api.step("5. Admin sign out", async () => {
    await signOut(page);
  });

  await api.step("6. Merchant sign in", async () => {
    await signIn(page, "Merchant panel", merchant.mobile);
    await expect(page).toHaveURL(/\/merchant\/dashboard$/);
  });

  await api.step("7. Merchant dashboard", async () => {
    await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
    await expect(page.getByText("Merchant panel").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "No team members yet" })).toBeVisible();
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: "Users" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Merchants" })).toHaveCount(0);
  });

  await api.step("8. Create driver", async () => {
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Delivery team" }).click();
    await expect(page.getByRole("heading", { name: "No team members yet" })).toBeVisible();
    await page.getByRole("link", { name: "Add team member" }).first().click();
    await page.getByRole("radio", { name: /Driver/ }).check();
    await page.getByLabel("Full name").fill(driver.name);
    await page.getByLabel("Mobile number").fill(driver.mobile);
    await page.getByLabel("Employee code").fill(driver.employeeCode);
    await page.getByRole("button", { name: "Add team member" }).click();
    await expect(page.getByText("Enter the driving licence number.").first()).toBeVisible();
    await page.getByLabel("Driving licence number").fill(driver.licence);
    await page.getByLabel("Licence expiry date").fill("2031-12-31");
    await page.getByRole("button", { name: "Add team member" }).click();
    await expect(page.getByRole("heading", { name: `${driver.name} has joined your delivery team` })).toBeVisible();
    await expect(page.getByText(/open the MBGA Delivery app and sign in/)).toBeVisible();
  });

  await api.step("9. Create helper", async () => {
    await page.getByRole("button", { name: "Add another team member" }).click();
    await page.getByRole("radio", { name: /Helper/ }).check();
    await expect(page.getByLabel("Driving licence number")).toHaveCount(0);
    await page.getByLabel("Full name").fill(helper.name);
    await page.getByLabel("Mobile number").fill(helper.mobile);
    await page.getByLabel("Employee code").fill(helper.employeeCode);
    await page.getByRole("button", { name: "Add team member" }).click();
    await expect(page.getByRole("heading", { name: `${helper.name} has joined your delivery team` })).toBeVisible();
  });

  await api.step("10. Delivery team list", async () => {
    await page.getByRole("link", { name: "Back to delivery team" }).click();
    const table = page.getByRole("table");
    await expect(table.getByRole("link", { name: driver.name })).toBeVisible();
    await expect(table.getByRole("link", { name: helper.name })).toBeVisible();
    await page.getByLabel("Type").selectOption("DRIVER");
    await expect(table.getByRole("link", { name: helper.name })).toHaveCount(0);
    await table.getByRole("link", { name: driver.name }).click();
    await expect(page.getByRole("heading", { name: driver.name, level: 1 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Driving licence" })).toBeVisible();
    await expect(page.getByText(driver.licence)).toBeVisible();
    await expect(page.getByText(formatMobile(driver.mobile)).first()).toBeVisible();
  });

  await api.step("11. Merchant sign out", async () => {
    await signOut(page);
    await page.goto("/merchant/delivery-team");
    await expect(page).toHaveURL(/\/login$/);
  });

  await report(testInfo, api.calls);
  const serverErrors = api.calls.filter((call) => call.status >= 500);
  expect(serverErrors, "no server errors during the journey").toEqual([]);
  const expected: Array<[string, string, number]> = [
    ["1. Super Admin sign in", "POST /admin/auth/otp/request", 202],
    ["1. Super Admin sign in", "POST /admin/auth/otp/verify", 200],
    ["1. Super Admin sign in", "GET /admin/auth/me", 200],
    ["4. Create test merchant", "POST /admin/merchants", 201],
    ["5. Admin sign out", "POST /admin/auth/logout", 204],
    ["6. Merchant sign in", "POST /merchant/auth/otp/request", 202],
    ["6. Merchant sign in", "POST /merchant/auth/otp/verify", 200],
    ["8. Create driver", "POST /merchant/delivery-users", 201],
    ["9. Create helper", "POST /merchant/delivery-users", 201],
    ["11. Merchant sign out", "POST /merchant/auth/logout", 204]
  ];
  for (const [step, call, status] of expected) {
    const [method, path] = call.split(" ");
    expect(
      api.calls.some((item) => item.step === step && item.method === method && item.path === path && item.status === status),
      `${step}: ${call} → ${status}`
    ).toBe(true);
  }
  // A merchant session never calls Admin APIs.
  const merchantSteps = api.calls.filter((call) => /^(6|7|8|9|10|11)\./.test(call.step));
  expect(merchantSteps.filter((call) => call.path.startsWith("/admin/"))).toEqual([]);
});
