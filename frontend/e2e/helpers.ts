import { expect, type Page } from "@playwright/test";

// Node globals without adding @types/node to the browser app.
declare const process: { env: Record<string, string | undefined> };

/**
 * Local/test data only. Seeded accounts come from `backend/scripts/seed_account_test_data.py`
 * and the development verification code configured in backend/.env (DEV_FIXED_OTP_CODE).
 * Nothing here is used by the production bundle. See docs/LOCAL_TEST_ACCOUNTS.md.
 */
export const E2E = {
  adminMobile: process.env.E2E_ADMIN_MOBILE ?? "9999900001",
  merchantMobile: process.env.E2E_MERCHANT_MOBILE ?? "9999900002",
  otp: process.env.E2E_OTP ?? "1234"
};

/**
 * Fixed identities for records the core journey creates. They match the cleanup rule in
 * backend/scripts/cleanup_e2e_test_data.py (code "E2E-…", names "E2E …", @example.invalid email)
 * and are removed before and after every run, so runs are repeatable and leave nothing behind.
 */
export const E2E_RECORDS = {
  merchant: {
    code: "E2E-WEB-M001",
    businessName: "E2E Web Merchant",
    contactName: "E2E Merchant Manager",
    mobile: "9999900011",
    email: "e2e.web.merchant@example.invalid"
  },
  driver: { name: "E2E Web Driver", mobile: "9999900012", employeeCode: "E2E-DRV-001", licence: "E2E-DL-0001" },
  helper: { name: "E2E Web Helper", mobile: "9999900013", employeeCode: "E2E-HLP-001" }
};

const RATE_LIMIT_MESSAGE = "Too many verification codes were requested";

export async function requestCode(page: Page, panel: "Admin panel" | "Merchant panel", mobile: string) {
  await expect(page.getByRole("heading", { name: "Welcome to MBGA" })).toBeVisible();
  // The radio is visually replaced by its label, so click what the user sees.
  await page.locator("label.segmented__option", { hasText: panel }).click();
  await expect(page.getByRole("radio", { name: panel })).toBeChecked();
  await page.getByLabel("Mobile number").fill(mobile);
  await page.getByRole("button", { name: "Send verification code" }).click();
  const otpGroup = page.getByRole("group", { name: "Verification code" });
  const alert = page.getByRole("alert");
  await expect(otpGroup.or(alert)).toBeVisible();
  if (await alert.isVisible()) {
    const text = (await alert.textContent()) ?? "";
    if (text.includes(RATE_LIMIT_MESSAGE)) {
      throw new Error(
        `The backend allows 5 verification codes per number per hour and +91 ${mobile} has reached it. ` +
          "Wait up to an hour before running the E2E suite again (the limit is intentionally not relaxed)."
      );
    }
    throw new Error(`Could not request a verification code for +91 ${mobile}: ${text}`);
  }
}

export async function typeCode(page: Page, code: string) {
  await page.getByLabel("Digit 1 of 4").click();
  await page.keyboard.type(code);
}

export async function signIn(page: Page, panel: "Admin panel" | "Merchant panel", mobile: string) {
  await requestCode(page, panel, mobile);
  await typeCode(page, E2E.otp);
}

export async function signOut(page: Page) {
  await page.getByRole("button", { name: /Open account menu/ }).click();
  await page.getByRole("menuitem", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Welcome to MBGA" })).toBeVisible();
  await expect(page.getByText("You have signed out.")).toBeVisible();
}

export function formatMobile(local: string) {
  return `+91 ${local.slice(0, 5)} ${local.slice(5)}`;
}

/** Text that must never reach the screen. */
export const FORBIDDEN_UI_TEXT = [
  /Traceback/i,
  /access_token|refresh_token|otp_hash|Bearer /i,
  /\b[A-Z]+_[A-Z_]{3,}\b/, // raw backend codes such as NUMBER_NOT_REGISTERED
  /"detail"\s*:/,
  /\b(RBAC|JWT|payload|endpoint|forbidden|unauthori[sz]ed)\b/i
];

export async function expectNoTechnicalText(page: Page) {
  const text = await page.locator("body").innerText();
  for (const pattern of FORBIDDEN_UI_TEXT) {
    expect(text, `screen text must not match ${pattern}`).not.toMatch(pattern);
  }
}
