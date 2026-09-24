import { expect, test } from "@playwright/test";

import { E2E, expectNoTechnicalText, requestCode, signOut, typeCode } from "./helpers";

const SESSION_KEY = "mbga.web.session.v1";

test.describe("sign-in and access (real backend)", () => {
  test("direct navigation to a protected page asks the user to sign in", async ({ page }) => {
    await page.goto("/admin/users?status=BLOCKED");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("radio", { name: "Admin panel" })).toBeChecked();
    await page.goto("/merchant/delivery-team");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("radio", { name: "Merchant panel" })).toBeChecked();
  });

  test("an invalid or expired session is discarded with a clear notice", async ({ page }) => {
    await page.goto("/login");
    await page.evaluate((key) => {
      window.sessionStorage.setItem(
        key,
        JSON.stringify({ channel: "admin", accessToken: "not-a-real-token", refreshToken: "not-a-real-token" })
      );
    }, SESSION_KEY);
    await page.goto("/admin/dashboard");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByText("Your session has ended. Please sign in again.")).toBeVisible();
    expect(await page.evaluate((key) => window.sessionStorage.getItem(key), SESSION_KEY)).toBeNull();
  });

  test("an unregistered number is not revealed and cannot sign in", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Mobile number").fill("7000000009");
    await page.getByRole("button", { name: "Send verification code" }).click();
    await expect(page.getByText(/has access to the Admin panel/)).toBeVisible();
    await typeCode(page, E2E.otp);
    await expect(page.getByRole("alert")).toHaveText("The verification code is incorrect. Please try again.");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("an invalid number is rejected before it reaches the server", async ({ page }) => {
    let requests = 0;
    page.on("request", (request) => {
      if (request.url().includes("/otp/request")) requests += 1;
    });
    await page.goto("/login");
    await page.getByLabel("Mobile number").fill("12345");
    await page.getByRole("button", { name: "Send verification code" }).click();
    await expect(page.getByText("Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9.")).toBeVisible();
    expect(requests).toBe(0);
  });

  test("a connection failure shows a friendly message", async ({ page }) => {
    await page.route("**/api/v1/admin/auth/otp/request", (route) => route.abort("connectionrefused"));
    await page.goto("/login");
    await page.getByLabel("Mobile number").fill(E2E.adminMobile);
    await page.getByRole("button", { name: "Send verification code" }).click();
    await expect(page.getByRole("alert")).toHaveText(
      "We could not connect to the server. Check your connection and try again."
    );
  });

  test("a server error never shows technical details", async ({ page }) => {
    await page.route("**/api/v1/admin/auth/otp/request", (route) =>
      route.fulfill({ status: 500, contentType: "text/plain", body: "Traceback (most recent call last): ValueError" })
    );
    await page.goto("/login");
    await page.getByLabel("Mobile number").fill(E2E.adminMobile);
    await page.getByRole("button", { name: "Send verification code" }).click();
    await expect(page.getByRole("alert")).toHaveText("The service is temporarily unavailable. Please try again.");
    await expect(page.getByText(/Traceback/)).toHaveCount(0);
  });

  test("merchant: wrong code, then sign in; admin pages are refused; mobile menu works", async ({ page }) => {
    await page.goto("/login");
    await requestCode(page, "Merchant panel", E2E.merchantMobile);
    await expect(page.getByText("+91 ••••• ••002")).toBeVisible();

    // Incorrect code.
    const wrong = E2E.otp === "0000" ? "1111" : "0000";
    await typeCode(page, wrong);
    await expect(page.getByRole("alert")).toHaveText("The verification code is incorrect. Please try again.");
    await expect(page.getByLabel("Digit 1 of 4")).toHaveValue("");

    // Correct code.
    await typeCode(page, E2E.otp);
    await expect(page).toHaveURL(/\/merchant\/dashboard$/);

    // A Merchant session cannot open Admin pages, and no Admin data is requested.
    const adminCalls: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("/api/v1/admin/")) adminCalls.push(request.url());
    });
    for (const path of ["/admin/merchants", "/admin/users", "/admin/roles", "/admin/permissions", "/admin/audit-logs"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { name: "This area is not part of your panel" })).toBeVisible();
    }
    expect(adminCalls).toEqual([]);
    await expectNoTechnicalText(page);
    await page.getByRole("link", { name: "Go to my dashboard" }).click();
    await expect(page).toHaveURL(/\/merchant\/dashboard$/);

    // Unreleased modules are clearly labelled, with no data.
    for (const path of ["customers", "orders", "inventory", "payments", "reports"]) {
      const apiCalls: string[] = [];
      const onRequest = (request: { url: () => string }) => {
        if (request.url().includes("/api/v1/") && !request.url().includes("/auth/me")) apiCalls.push(request.url());
      };
      page.on("request", onRequest);
      await page.goto(`/merchant/${path}`);
      await expect(page.getByText("This feature is not available in the current backend release.")).toBeVisible();
      await expect(page.getByRole("table")).toHaveCount(0);
      await expect(page.locator(".stat-card")).toHaveCount(0);
      page.off("request", onRequest);
      expect(apiCalls, `/merchant/${path} must not load data`).toEqual([]);
    }

    // Small screens: the sidebar becomes a drawer.
    await page.setViewportSize({ width: 390, height: 844 });
    const sidebar = page.getByRole("complementary", { name: "Merchant panel navigation" });
    await expect(sidebar).toBeHidden();
    await page.getByRole("button", { name: "Open menu" }).click();
    await expect(sidebar).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(sidebar).toBeHidden();
    await page.getByRole("button", { name: "Open menu" }).click();
    await sidebar.getByRole("link", { name: "Delivery team" }).click();
    await expect(page).toHaveURL(/\/merchant\/delivery-team$/);
    await expect(sidebar).toBeHidden();
    await expect(page.getByRole("heading", { name: "Delivery team", level: 1 })).toBeVisible();

    await page.setViewportSize({ width: 1280, height: 800 });
    await signOut(page);
  });
});
