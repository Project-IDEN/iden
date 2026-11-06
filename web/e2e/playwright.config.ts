import { defineConfig, devices } from "@playwright/test";
import { DASHBOARD } from "./support/iden";

/**
 * End-to-end tests against the local docker compose stack only: the dashboard
 * on :3000, the Auth UI on :4000 and the provider on :8000. See README.md.
 *
 * One worker, in order: every test signs in through the same provider, whose
 * per-address sign-in limit (30 per five minutes) the whole run shares.
 */
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  globalSetup: "./global-setup.ts",
  globalTeardown: "./global-teardown.ts",
  outputDir: "../../test-results/e2e-artifacts",
  reporter: [
    ["list"],
    ["junit", { outputFile: "../../test-results/e2e.xml" }],
    ["html", { outputFolder: "../../test-results/e2e-report", open: "never" }],
  ],
  use: {
    baseURL: DASHBOARD,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
