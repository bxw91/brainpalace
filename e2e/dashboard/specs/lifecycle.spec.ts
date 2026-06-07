/**
 * Headline lifecycle E2E (spec acceptance §13): drive the whole feature against
 * a real control plane + a throwaway project server.
 *
 * Journey: Overview → Instances (start the seeded instance) → Folders (add a
 * folder, watch the index job) → Queries (run a query, see it in history) →
 * Config (change an enum click-only, Save+Restart, confirm it persisted) →
 * Instances (stop).
 *
 * Ordering note (deliberate deviation from the plan's illustrative snippet): the
 * folder-index + query steps run BEFORE the Config enum Save+Restart. The seeded
 * project boots with OpenAI embeddings so index/query are *real*; doing them
 * first keeps a working embedding provider during retrieval, while the
 * Save+Restart-and-persist checkpoint still runs end-to-end right before Stop.
 * Every `expect` from the plan snippet is preserved.
 */
import { test, expect } from "@playwright/test";
import { readState, BROWSER_UNAVAILABLE } from "../fixtures/state";

test.skip(
  BROWSER_UNAVAILABLE,
  "Browser cannot launch in this sandbox (BROWSER_UNAVAILABLE). " +
    "Run elsewhere with: cd e2e/dashboard && npx playwright test",
);

test("manage an instance end to end", async ({ page }) => {
  const state = readState();

  // --- Overview ---------------------------------------------------------
  // baseURL ends in /dashboard/; "./" lands on the SPA root (not the origin /).
  await page.goto("./");
  await expect(page.getByTestId("tab-overview")).toBeVisible();
  await expect(page.getByTestId("tabbar")).toContainText(/instances/i);

  // --- Instances: the seeded "itest" project appears; start it. ---------
  await page.getByTestId("tab-link-instances").click();
  const row = page.getByRole("row", { name: /itest/i });
  await expect(row).toBeVisible();

  // It starts as a stopped, Start-able instance — bring it up.
  await row.getByRole("button", { name: /^start$/i }).click();
  // Wait for it to become running (status cell flips; Stop becomes available).
  await expect(row.getByRole("button", { name: /^stop$/i })).toBeVisible({
    timeout: 60_000,
  });

  // The instance auto-selects (only one in the fleet), enabling instance tabs.

  // A freshly started server has a brief window where the BFF proxy can't reach
  // it yet (it returns 502 → the tab would flash its "stopped" state). Wait for
  // the proxied folders endpoint to become reachable before driving data tabs.
  const instances = (await (
    await page.request.get("api/instances")
  ).json()) as Array<{ id: string; name: string }>;
  const itest = instances.find((i) => i.name === "itest");
  expect(itest, "seeded itest instance present").toBeTruthy();
  await expect
    .poll(
      async () =>
        (await page.request.get(`api/instances/${itest!.id}/folders`)).status(),
      { timeout: 30_000, intervals: [500] },
    )
    .toBe(200);

  // --- Folders: add a folder, watch a job complete. ---------------------
  await page.getByTestId("tab-link-folders").click();
  await expect(page.getByTestId("tab-folders")).toBeVisible();
  await page.getByTestId("btn-add-folder").click();
  const picker = page.getByTestId("folder-picker");
  await expect(picker).toBeVisible();
  await picker.getByTestId("input-folder-path").fill(state.indexDir);
  await picker.getByTestId("btn-folder-add").click();

  // A job appears (indexing or already completed) — proves the index pipeline
  // accepted the folder and ran against the real server.
  await expect(page.getByTestId("job-progress")).toBeVisible({ timeout: 30_000 });
  // The folder eventually shows up in the table.
  await expect(
    page.getByTestId(`folder-row-${state.indexDir}`),
  ).toBeVisible({ timeout: 60_000 });

  // --- Queries: run a query via the composer; see results + history. ----
  await page.getByTestId("tab-link-queries").click();
  await expect(page.getByTestId("tab-queries")).toBeVisible();
  await page.getByTestId("btn-new-query").click();
  await expect(page.getByTestId("query-composer")).toBeVisible();
  await page.getByTestId("input-run-query").fill("hello");
  await page.getByTestId("btn-run-query").click();
  // Fresh results render (the seeded greeting.js contains the "hello" token).
  await expect(page.getByTestId("run-results")).toBeVisible({ timeout: 30_000 });
  // The query is logged and shows up in the history table.
  await expect(page.getByRole("row", { name: /hello/i })).toBeVisible({
    timeout: 30_000,
  });

  // --- Config: change an enum click-only, Save + Restart, persist. ------
  await page.getByTestId("tab-link-config").click();
  await expect(page.getByTestId("tab-config")).toBeVisible();
  // Switch the reranker provider (harmless to embedding/retrieval) to "ollama".
  const enumOllama = page.getByTestId("enum-reranker.provider-ollama");
  await expect(enumOllama).toBeVisible();
  await enumOllama.click();
  await expect(enumOllama).toHaveAttribute("data-selected", "true");

  await page.getByTestId("btn-save-restart").click();
  // A success toast confirms the save (and restart) landed.
  await expect(page.getByTestId("toast-success")).toContainText(/saved/i, {
    timeout: 60_000,
  });

  // Reopen Config → value persisted to disk and reloaded.
  await page.getByTestId("tab-link-overview").click();
  await page.getByTestId("tab-link-config").click();
  await expect(
    page.getByTestId("enum-reranker.provider-ollama"),
  ).toHaveAttribute("data-selected", "true", { timeout: 30_000 });

  // --- Stop the instance from the Instances tab. ------------------------
  await page.getByTestId("tab-link-instances").click();
  const row2 = page.getByRole("row", { name: /itest/i });
  await row2.getByRole("button", { name: /^stop$/i }).click();
  await page.getByTestId("confirm-dialog").getByTestId("btn-confirm").click();
  // Once stopped, the Start button comes back for this row.
  await expect(row2.getByRole("button", { name: /^start$/i })).toBeVisible({
    timeout: 30_000,
  });
});
