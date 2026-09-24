import { expect, test } from "@playwright/test";

/** Contract-level check with mocked API responses (no backend or verification code needed). */
test("admin login uses exactly four OTP boxes and submits four digits", async ({ page }) => {
  let submittedOtp = "";
  let submittedMobile = "";

  await page.route("**/api/v1/admin/auth/otp/request", async (route) => {
    submittedMobile = (route.request().postDataJSON() as { mobile_number: string }).mobile_number;
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({
        request_id: "request-1",
        message: "OTP request accepted",
        expires_in: 300,
        resend_after: 30,
        code: "OTP_REQUEST_ACCEPTED"
      })
    });
  });

  await page.route("**/api/v1/admin/auth/otp/verify", async (route) => {
    const body = route.request().postDataJSON() as { otp: string };
    submittedOtp = body.otp;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        token: {
          access_token: "access-token",
          refresh_token: "refresh-token",
          token_type: "Bearer",
          expires_in: 900
        },
        user_id: "user-1",
        login_channel: "ADMIN",
        code: "OTP_VERIFIED",
        message: "OTP verified"
      })
    });
  });

  await page.route("**/api/v1/admin/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        user_id: "user-1",
        display_name: "Admin User",
        mobile_number: "+919876543210",
        login_channel: "ADMIN",
        active_roles: ["super_admin"],
        effective_permissions: ["dashboard.view"],
        status: "ACTIVE"
      })
    });
  });

  await page.route("**/api/v1/admin/dashboard/summary", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        users: 3,
        active_users: 3,
        blocked_users: 0,
        roles: 8,
        active_roles: 8,
        permissions: 83,
        active_permissions: 83,
        active_sessions: 1,
        audit_logs: 0
      })
    });
  });

  await page.goto("/");
  await page.getByLabel("Mobile number").fill("98765 43210");
  await page.getByRole("button", { name: "Send verification code" }).click();

  const boxes = page.getByRole("group", { name: "Verification code" }).getByRole("textbox");
  await expect(boxes).toHaveCount(4);
  expect(submittedMobile).toBe("+919876543210");

  await page.getByLabel("Digit 1 of 4").fill("1");
  await page.getByLabel("Digit 2 of 4").fill("2");
  await page.getByLabel("Digit 3 of 4").fill("3");
  await page.getByLabel("Digit 4 of 4").fill("4");

  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  expect(submittedOtp).toBe("1234");
  // Only the dashboard permission was granted, so only the dashboard appears in the menu.
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: "Dashboard" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Users" })).toHaveCount(0);
});
