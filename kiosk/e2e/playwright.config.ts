import { defineConfig } from "@playwright/test";

const RESULTS = process.env.M07_RESULTS_DIR ?? "../../test-results-m07";

/**
 * Sheet M07, against the local stack only: the provider on :8000 and the real
 * kiosk server on 127.0.0.1:8080 serving the built kiosk client. See README.md.
 *
 * One worker, in file order: the cases share one kiosk, and pairing it (TC-197)
 * is what every later case stands on.
 */
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  globalSetup: "./global-setup.ts",
  globalTeardown: "./global-teardown.ts",
  outputDir: `${RESULTS}/artifacts`,
  reporter: [
    ["list"],
    ["junit", { outputFile: `${RESULTS}/m07.xml` }],
    ["json", { outputFile: `${RESULTS}/results.json` }],
    ["html", { outputFolder: `${RESULTS}/report`, open: "never" }],
  ],
  use: { trace: "retain-on-failure" },
  webServer: {
    command: "node scripts/start-kiosk.mjs --fresh",
    url: "http://127.0.0.1:8080/api/state",
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
