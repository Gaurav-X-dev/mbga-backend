import { defineConfig, devices } from "@playwright/test";

/**
 * E2E runs against the local backend (http://127.0.0.1:8005) with seeded test accounts.
 * Tests run one at a time: the backend limits verification-code requests per mobile number
 * (5 per hour). One full run uses one request each for the seeded Super Admin, the seeded
 * merchant and the E2E merchant.
 */
export default defineConfig({
  testDir: "./e2e",
  // Removes E2E-marked records before and after each run (local/dev/test databases only).
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 20_000 },
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure"
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] }
    }
  ],
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: true
  }
});
