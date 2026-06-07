/**
 * Playwright config for the BrainPalace control-plane dashboard E2E suite.
 *
 * Global setup spins up a real dashboard against a hermetic sandbox; specs drive
 * a headless Chromium browser against it. Teardown stops everything.
 *
 * Browser availability: in CI / a normal dev box, `npx playwright install
 * chromium` makes headless Chromium runnable. In a locked-down sandbox where the
 * browser genuinely cannot launch, set `BROWSER_UNAVAILABLE=1` to skip the
 * browser-driven specs (they remain committed + runnable elsewhere). See the
 * `e2e/dashboard/README.md` for the exact command a human runs.
 */
import { defineConfig, devices } from "@playwright/test";
import { BASE_URL } from "./fixtures/paths";

export default defineConfig({
  testDir: "./specs",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? "list" : [["list"], ["html", { open: "never" }]],
  // The headline flow indexes + queries against a real server; give it room.
  timeout: 90_000,
  expect: { timeout: 15_000 },
  globalSetup: "./global-setup.ts",
  globalTeardown: "./global-teardown.ts",
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
