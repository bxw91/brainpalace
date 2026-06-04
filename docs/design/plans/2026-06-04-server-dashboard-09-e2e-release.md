# Dashboard Plan 09 — E2E + a11y/polish + release

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development / executing-plans. Read [index](2026-06-04-server-dashboard-00-index.md). Depends on plans 01–08. Final plan.

**Goal:** Prove the whole feature works end-to-end with Playwright, pass an accessibility/polish bar, then cut a release per `docs/RELEASING.md`.

**Architecture:** Playwright drives a real browser against a real control plane + a throwaway project server. Tests cover the headline flow from the spec acceptance criteria. Polish = empty/loading/error states, keyboard nav, contrast.

**Tech Stack:** Playwright, Vitest, Taskfile, release tooling (GitHub Release → PyPI OIDC).

---

## File Structure
- Create `e2e/dashboard/` — Playwright config + specs + fixtures.
- Modify `Taskfile.yml` — `test:e2e-dashboard` target.
- Polish edits across `frontend/src/**`.
- Release edits: `docs/CHANGELOG.md`, version bumps in all four `pyproject.toml` + `__init__.py`.

---

### Task 9.1: Playwright harness + fixtures

**Files:** Create `e2e/dashboard/playwright.config.ts`, `e2e/dashboard/fixtures/project.ts`, `e2e/dashboard/global-setup.ts`.

- [ ] **Step 1: Install + scaffold**

Run:
```bash
cd e2e/dashboard && npm init -y && npm install -D @playwright/test && npx playwright install --with-deps chromium
```

- [ ] **Step 2: Global setup** — a script that:
  1. Creates a temp project dir with a minimal `.brainpalace/config.yaml` (chroma backend, auto_port).
  2. Launches the control plane: `brainpalace dashboard start --no-open --port 8799` (or `uvicorn ... --port 8799`), waits for `/dashboard/api/health`.
  3. Registers/starts the temp project instance through the API so the UI has one row.
  4. Exposes `baseURL=http://127.0.0.1:8799/dashboard/` to specs; tears everything down in global-teardown (stop instance + stop dashboard, rm temp dir).

- [ ] **Step 3: Commit** (`test(e2e): dashboard Playwright harness`).

---

### Task 9.2: Headline E2E flow (spec acceptance §13)

**Files:** Create `e2e/dashboard/specs/lifecycle.spec.ts`.

- [ ] **Step 1: Write the spec** covering the full journey (each `expect` is a checkpoint):

```ts
import { test, expect } from "@playwright/test";

test("manage an instance end to end", async ({ page }) => {
  await page.goto("/");                                   // Overview
  await expect(page.getByText(/instances/i)).toBeVisible();

  // Instances tab: the seeded project appears and is running.
  await page.getByRole("link", { name: "Instances" }).click();
  const row = page.getByRole("row", { name: /itest/i });
  await expect(row).toBeVisible();

  // Config: change an enum (click-only) and Save+Restart.
  await page.getByRole("link", { name: "Config" }).click();
  await page.getByRole("button", { name: "ollama" }).click();      // embedding.provider enum
  await page.getByRole("button", { name: /save \+ restart/i }).click();
  await expect(page.getByText(/saved/i)).toBeVisible();

  // Reopen Config → value persisted.
  await page.getByRole("link", { name: "Config" }).click();
  await expect(page.getByRole("button", { name: "ollama" })).toHaveAttribute("data-selected", "true");

  // Folders: add a folder, watch a job complete.
  await page.getByRole("link", { name: "Folders" }).click();
  await page.getByRole("button", { name: /add folder/i }).click();
  await page.getByLabel(/path/i).fill(process.env.E2E_INDEX_DIR!);
  await page.getByRole("button", { name: /^add$/i }).click();
  await expect(page.getByText(/indexing|completed/i)).toBeVisible({ timeout: 30000 });

  // Queries: run a query via replay, see it in history.
  await page.getByRole("link", { name: "Queries" }).click();
  await page.getByRole("button", { name: /run query|new query/i }).click();
  await page.getByLabel(/query/i).fill("hello");
  await page.getByRole("button", { name: /^run$/i }).click();
  await expect(page.getByText(/results/i)).toBeVisible();
  await expect(page.getByRole("row", { name: /hello/i })).toBeVisible();

  // Stop the instance from Instances tab.
  await page.getByRole("link", { name: "Instances" }).click();
  await row.getByRole("button", { name: /stop/i }).click();
  await page.getByRole("button", { name: /confirm/i }).click();
  await expect(row.getByTestId(/status-/)).toHaveAttribute("data-status", "stopped");
});
```

- [ ] **Step 2: Run** `npx playwright test` (headless). Iterate selectors against the real UI until green. Add `data-selected` / `data-testid` attributes to components as needed (small edits to plan-05/06 components).
- [ ] **Step 3: Taskfile** add `test:e2e-dashboard`. **Step 4: Commit** (`test(e2e): headline dashboard lifecycle flow`).

---

### Task 9.3: Empty / loading / error states

**Files:** `frontend/src/**` (tabs + components). Tests: extend Vitest tab tests.

- [ ] **Step 1: Failing tests** — for each tab: a loading skeleton renders while query pending; an error banner renders on a rejected query (mock reject); an empty state renders when data is `[]` (e.g. "No folders indexed yet — add one").
- [ ] **Step 2: Implement** skeletons, error banners (with retry button), empty states across all tabs. Overview shows "No instances — run `brainpalace start` in a project" when fleet empty.
- [ ] **Step 3: Run → PASS. Step 4: Commit** (`feat(dashboard-ui): loading/empty/error states`).

---

### Task 9.4: Accessibility + keyboard nav + contrast

**Files:** `frontend/src/**`. Test: `e2e/dashboard/specs/a11y.spec.ts`.

- [ ] **Step 1:** Add `@axe-core/playwright`; write an a11y spec asserting no serious/critical violations on Overview, Instances, Config.
- [ ] **Step 2:** Fix violations: focus rings, `aria-label`s on icon buttons, tab order, dialog focus-trap in ConfirmDialog, sufficient contrast (verify theme tokens). Ensure all tabs reachable by keyboard; enum/toggle controls operable via keyboard.
- [ ] **Step 3:** `npx playwright test specs/a11y.spec.ts` → PASS. **Step 4: Commit** (`fix(dashboard-ui): accessibility pass`).

---

### Task 9.5: Performance sanity (poll batching)

**Files:** `frontend/src/state/*`, backend events.

- [ ] **Step 1:** Verify the SPA opens ONE `/dashboard/api/events` SSE stream (not N polls) for instance freshness; per-tab data uses TanStack Query with sane `staleTime` (e.g. 3–5s) and only the active tab polls.
- [ ] **Step 2:** Add a Vitest/assertion or a manual note in `docs/DASHBOARD.md` "Performance" subsection describing the polling model. Confirm no tab sets `refetchInterval` < 1500ms.
- [ ] **Step 3: Commit** (`perf(dashboard): single SSE stream + bounded polling`).

---

### Task 9.6: Full gate + release

- [ ] **Step 1:** `cd brainpalace-dashboard/frontend && npm run build` → refresh `static/`; commit.
- [ ] **Step 2:** Run the complete gate:
```bash
export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
task before-push          # includes lint:dashboard-parity + doc-freshness
cd brainpalace-dashboard/frontend && npx vitest run
cd ../../e2e/dashboard && npx playwright test
```
Expected: all green.
- [ ] **Step 3:** Version bump: set the SAME new version in `brainpalace-server/pyproject.toml`, `brainpalace-cli/pyproject.toml`, `brainpalace-dashboard/pyproject.toml`, and the three `__init__.py` `__version__` (the version-consistency test enforces this). Add a `docs/CHANGELOG.md` release section summarizing the dashboard.
- [ ] **Step 4:** Follow `docs/RELEASING.md` exactly to cut the release (GitHub Release → PyPI via OIDC). **Do not** `poetry publish` by hand. **Do not** push the local `stable` branch.
- [ ] **Step 5: Commit** the release prep (`chore(release): BrainPalace <version> — control-plane dashboard`).

---

## Plan 09 self-check (== whole-feature acceptance, spec §13)
- [ ] `brainpalace dashboard` opens a professional tabbed UI listing all instances.
- [ ] Start/stop/restart per project works from the UI.
- [ ] Every config option editable click-only; Save and Save+Restart both work; batched.
- [ ] Real per-instance stats render across tabs.
- [ ] Query history ≥2 days visible, filterable, replayable.
- [ ] A new config/CLI/endpoint fails `task before-push` until surfaced (proven in plan 08 self-check).
- [ ] `task before-push` + Vitest + Playwright all green; release cut per RELEASING.md.
