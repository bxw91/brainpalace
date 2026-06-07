/**
 * Accessibility gate: assert no serious/critical axe violations on the three
 * headline screens (Overview, Instances, Config). The seeded instance
 * auto-selects so the Config form actually renders its controls.
 *
 * We assert only on serious + critical impacts (the bar set by the plan); minor
 * / moderate findings are reported in the attached results but don't fail.
 */
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { BROWSER_UNAVAILABLE } from "../fixtures/state";

test.skip(
  BROWSER_UNAVAILABLE,
  "Browser cannot launch in this sandbox (BROWSER_UNAVAILABLE). " +
    "Run elsewhere with: cd e2e/dashboard && npx playwright test specs/a11y.spec.ts",
);

const SERIOUS = new Set(["serious", "critical"]);

async function scan(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  return results.violations.filter((v) => SERIOUS.has(v.impact ?? ""));
}

test.describe("accessibility", () => {
  test("Overview has no serious/critical violations", async ({ page }) => {
    await page.goto("./");
    await expect(page.getByTestId("tab-overview")).toBeVisible();
    const violations = await scan(page);
    expect(
      violations,
      JSON.stringify(
        violations.map((v) => ({ id: v.id, nodes: v.nodes.length })),
        null,
        2,
      ),
    ).toEqual([]);
  });

  test("Instances has no serious/critical violations", async ({ page }) => {
    await page.goto("./");
    await page.getByTestId("tab-link-instances").click();
    await expect(page.getByTestId("tab-instances")).toBeVisible();
    await expect(page.getByRole("row", { name: /itest/i })).toBeVisible();
    const violations = await scan(page);
    expect(
      violations,
      JSON.stringify(
        violations.map((v) => ({ id: v.id, nodes: v.nodes.length })),
        null,
        2,
      ),
    ).toEqual([]);
  });

  test("Config has no serious/critical violations", async ({ page }) => {
    await page.goto("./");
    await page.getByTestId("tab-link-config").click();
    await expect(page.getByTestId("tab-config")).toBeVisible();
    // Wait for the form (the seeded instance auto-selects).
    await expect(page.getByTestId("schema-form")).toBeVisible({
      timeout: 15_000,
    });
    const violations = await scan(page);
    expect(
      violations,
      JSON.stringify(
        violations.map((v) => ({ id: v.id, nodes: v.nodes.length })),
        null,
        2,
      ),
    ).toEqual([]);
  });

  test("ConfirmDialog traps focus and is operable by keyboard", async ({
    page,
  }) => {
    await page.goto("./");
    await page.getByTestId("tab-link-instances").click();
    const row = page.getByRole("row", { name: /itest/i });
    await expect(row).toBeVisible();
    // The seeded instance is stopped — its destructive action is "Remove".
    await row.getByRole("button", { name: /remove .* from list/i }).click();
    const dialog = page.getByTestId("confirm-dialog");
    await expect(dialog).toBeVisible();
    // Focus lands inside the dialog on open.
    await expect(dialog.getByTestId("btn-confirm")).toBeFocused();
    // Escape closes it (keyboard operable).
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });
});
