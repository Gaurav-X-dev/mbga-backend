import { expect, test } from "@playwright/test";

test("admin login uses exactly four OTP boxes and submits four digits", async ({ page }) => {
  let submittedOtp = "";

  await page.route("**/api/v1/admin/auth/otp/request", async (route) => {
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
          token_type: "bearer",
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

  await page.goto("/");
  await page.getByLabel("Mobile number").fill("+919876543210");
  await page.getByRole("button", { name: "Request OTP" }).click();

  await expect(page.getByText("We have sent a 4-digit code.")).toBeVisible();
  await expect(page.locator(".otp-boxes input")).toHaveCount(4);

  await page.getByLabel("OTP digit 1").fill("1");
  await page.getByLabel("OTP digit 2").fill("2");
  await page.getByLabel("OTP digit 3").fill("3");
  await page.getByLabel("OTP digit 4").fill("4");
  await page.getByRole("button", { name: "Verify OTP" }).click();

  expect(submittedOtp).toBe("1234");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
});
