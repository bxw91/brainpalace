# Dashboard Plan 05 — SPA foundation + SchemaForm + Overview/Instances/Config tabs

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development / executing-plans. Read [index](2026-06-04-server-dashboard-00-index.md). Depends on plans 01–03 (uses instances/schema/config/data endpoints). Frontend skill: invoke **`frontend`** skill before writing components (distinctive, non-generic UI).

**Goal:** Build the React/TS SPA shell (sidebar instance picker + tabbed layout), the data-driven `SchemaForm`, and the first three tabs (Overview, Instances, Config) with batched Save / Save+Restart. Serve the built SPA from FastAPI.

**Architecture:** Vite + React 18 + TS + Tailwind. TanStack Query for server state + polling; TanStack Router for tabs. Zod-typed API client. `SchemaForm` renders controls purely from `GET /dashboard/api/schema`. Build output → `brainpalace_dashboard/static/`, served via FastAPI `StaticFiles` with SPA fallback.

**Tech Stack:** Vite, React 18, TypeScript, Tailwind, TanStack Query + Router, Recharts, Zod, lucide-react, Vitest, Testing Library.

---

## File Structure
- Create `brainpalace-dashboard/frontend/` — Vite project (package.json, vite.config.ts, tsconfig.json, tailwind.config.ts, index.html).
- `frontend/src/api/{client.ts,types.ts}` — fetch wrappers + Zod schemas.
- `frontend/src/app.tsx`, `router.tsx`, `main.tsx` — shell + routing.
- `frontend/src/components/` — `Sidebar`, `StatCard`, `DataTable`, `Toast`, `ConfirmDialog`, `SchemaForm/*`.
- `frontend/src/tabs/` — `Overview.tsx`, `Instances.tsx`, `Config.tsx`.
- Modify `brainpalace_dashboard/app.py` — mount `StaticFiles` + SPA fallback.
- Modify `Taskfile.yml` — `build:dashboard-ui` target.

---

### Task 5.1: Vite project scaffold + build wired into FastAPI

**Files:**
- Create the Vite project under `frontend/`; configure `build.outDir = "../brainpalace_dashboard/static"`.
- Modify `app.py`.
- Test: `brainpalace-dashboard/tests/test_static_mount.py`

- [ ] **Step 1: Scaffold Vite**

Run:
```bash
cd brainpalace-dashboard
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install
npm install @tanstack/react-query @tanstack/react-router recharts zod lucide-react
npm install -D tailwindcss postcss autoprefixer vitest @testing-library/react @testing-library/jest-dom jsdom
npx tailwindcss init -p
```

- [ ] **Step 2: Configure build output + base path**

`frontend/vite.config.ts`:
```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/dashboard/",
  build: { outDir: "../brainpalace_dashboard/static", emptyOutDir: true },
  test: { environment: "jsdom", setupFiles: ["./src/test-setup.ts"], globals: true },
});
```
Create `frontend/src/test-setup.ts` with `import "@testing-library/jest-dom";`.
Configure `tailwind.config.ts` `content: ["./index.html", "./src/**/*.{ts,tsx}"]` and add Tailwind directives to `src/index.css`.

- [ ] **Step 3: Write the failing backend test for static mount**

```python
# brainpalace-dashboard/tests/test_static_mount.py
from fastapi.testclient import TestClient
from brainpalace_dashboard.app import create_app

def test_spa_served_at_dashboard_root(tmp_path, monkeypatch):
    # point the app at a fixture static dir containing index.html
    static = tmp_path / "static"; static.mkdir()
    (static / "index.html").write_text("<html><body>BrainPalace</body></html>")
    monkeypatch.setenv("BRAINPALACE_DASHBOARD_STATIC", str(static))
    client = TestClient(create_app())
    resp = client.get("/dashboard/")
    assert resp.status_code == 200
    assert "BrainPalace" in resp.text
```

- [ ] **Step 4: Implement static mount + SPA fallback in `app.py`**

```python
import os
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

def _static_dir() -> Path:
    return Path(os.environ.get("BRAINPALACE_DASHBOARD_STATIC",
                               Path(__file__).parent / "static"))

# in create_app(), AFTER including API routers:
    static = _static_dir()
    if (static / "index.html").exists():
        app.mount("/dashboard/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/dashboard/{path:path}")
        def spa(path: str):
            candidate = static / path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(static / "index.html")
```

> Order matters: API routers are registered with their own prefixes (`/dashboard/api/...`) before this catch-all, so they win. Verify by running the existing route tests after adding the catch-all.

- [ ] **Step 5: Build + run tests**

Run: `cd frontend && npm run build` then `cd .. && poetry run pytest tests/test_static_mount.py tests/test_routes_instances.py -v`
Expected: PASS (SPA served; API routes still work).

- [ ] **Step 6: Taskfile target + commit**

Add to `Taskfile.yml`: `build:dashboard-ui` → `cd brainpalace-dashboard/frontend && npm ci && npm run build`. Add `frontend/node_modules` and (decide) whether `static/` is committed — commit built `static/` so `pip install` users get the UI; add a note. Commit:
```bash
git add brainpalace-dashboard/frontend brainpalace-dashboard/brainpalace_dashboard/static brainpalace-dashboard/brainpalace_dashboard/app.py brainpalace-dashboard/tests/test_static_mount.py Taskfile.yml
git commit -m "feat(dashboard): Vite SPA scaffold served by FastAPI

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5.2: Typed API client + Zod types

**Files:**
- Create `frontend/src/api/types.ts`, `frontend/src/api/client.ts`
- Test: `frontend/src/api/client.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/api/client.test.ts
import { describe, it, expect, vi } from "vitest";
import { listInstances } from "./client";

describe("api client", () => {
  it("parses instances", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify([{ id: "a", name: "foo", status: "running",
        base_url: "http://x", project_root: "/p/foo", pid: 1, mode: "project", started_at: "" }]),
      { status: 200, headers: { "content-type": "application/json" } })));
    const rows = await listInstances();
    expect(rows[0].id).toBe("a");
  });
});
```

- [ ] **Step 2: Implement types + client**

```ts
// frontend/src/api/types.ts
import { z } from "zod";

export const Instance = z.object({
  id: z.string(), name: z.string(),
  status: z.enum(["running", "unhealthy", "stopped", "stale"]),
  base_url: z.string(), project_root: z.string(),
  pid: z.number(), mode: z.string(), started_at: z.string(),
});
export type Instance = z.infer<typeof Instance>;

export const SchemaField = z.object({
  key: z.string(), dotpath: z.string(), label: z.string(),
  widget: z.enum(["enum", "toggle", "int", "text", "group"]),
  secret: z.boolean().optional(),
  options: z.array(z.string()).optional(),
  presets: z.array(z.string()).optional(),
  placeholder: z.string().optional(),
  min: z.number().optional(), max: z.number().optional(), step: z.number().optional(),
  help: z.string().optional(),
  visible_when: z.object({ field: z.string(), equals: z.string() }).optional(),
  fields: z.array(z.any()).optional(),
});
export const UiSchema = z.object({
  sections: z.array(z.object({ key: z.string(), label: z.string(), fields: z.array(SchemaField) })),
});
export type UiSchema = z.infer<typeof UiSchema>;
```

```ts
// frontend/src/api/client.ts
import { Instance, UiSchema } from "./types";

const BASE = "/dashboard/api";

async function get<T>(path: string, parse: (j: unknown) => T): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail ?? r.statusText);
  return parse(await r.json());
}

export const listInstances = () =>
  get("/instances", (j) => Instance.array().parse(j));
export const getSchema = () =>
  get("/schema", (j) => UiSchema.parse(j));
export const getConfig = (id: string) =>
  get(`/instances/${id}/config`, (j) => j as Record<string, any>);

export async function patchConfig(id: string, values: Record<string, any>, restart: boolean) {
  const r = await fetch(`${BASE}/instances/${id}/config`, {
    method: "PATCH", headers: { "content-type": "application/json" },
    body: JSON.stringify({ values, restart }),
  });
  if (!r.ok) throw await r.json();      // {errors:[...]} on 422
  return r.json();
}
export const startInstance = (id: string) => fetch(`${BASE}/instances/${id}/start`, { method: "POST" }).then(r => r.json());
export const stopInstance = (id: string) => fetch(`${BASE}/instances/${id}/stop`, { method: "POST" }).then(r => r.json());
export const restartInstance = (id: string) => fetch(`${BASE}/instances/${id}/restart`, { method: "POST" }).then(r => r.json());
export const registerProject = (path: string) => fetch(`${BASE}/instances/register`, { method: "POST", headers: {"content-type":"application/json"}, body: JSON.stringify({ path }) }).then(r => r.json());
export const forgetInstance = (id: string) => fetch(`${BASE}/instances/${id}`, { method: "DELETE" }).then(r => r.json());
```

- [ ] **Step 3: Run** → `cd frontend && npx vitest run src/api/client.test.ts` → PASS.
- [ ] **Step 4: Commit**

```bash
git add brainpalace-dashboard/frontend/src/api
git commit -m "feat(dashboard-ui): typed API client + Zod types

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5.3: App shell — sidebar instance picker + tabbed layout

**Files:**
- Create `frontend/src/app.tsx`, `frontend/src/router.tsx`, `frontend/src/main.tsx`
- Create `frontend/src/components/Sidebar.tsx`
- Create `frontend/src/state/selectedInstance.ts` (React context)
- Test: `frontend/src/components/Sidebar.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/Sidebar.test.tsx
import { render, screen } from "@testing-library/react";
import { Sidebar } from "./Sidebar";

it("renders instances with status dots", () => {
  render(<Sidebar instances={[
    { id: "a", name: "foo", status: "running" } as any,
    { id: "b", name: "bar", status: "stopped" } as any,
  ]} selectedId="a" onSelect={() => {}} />);
  expect(screen.getByText("foo")).toBeInTheDocument();
  expect(screen.getByText("bar")).toBeInTheDocument();
  expect(screen.getByTestId("status-a")).toHaveAttribute("data-status", "running");
});
```

- [ ] **Step 2: Implement `Sidebar.tsx`** (status dot colors: running=emerald, unhealthy=amber, stopped=slate, stale=red). Build the shell `app.tsx` with `QueryClientProvider`, a `useQuery(["instances"], listInstances, { refetchInterval: 5000 })`, a selected-instance context, sidebar + `<Outlet/>` for the active tab. `router.tsx` defines routes: `/` (Overview), `/instances`, `/config`, plus the later tabs as lazy stubs.

> Follow the `frontend` skill output for visual quality: cohesive dark theme, 8px grid, real spacing, no default-bootstrap look. Status dot is a small `<span data-testid={"status-"+id} data-status={status} className=...>`.

- [ ] **Step 3: Run** → `npx vitest run src/components/Sidebar.test.tsx` → PASS.
- [ ] **Step 4: Commit** (`feat(dashboard-ui): app shell + sidebar instance picker`).

---

### Task 5.4: `SchemaForm` — render every widget from UISchema, batched edits

**Files:**
- Create `frontend/src/components/SchemaForm/SchemaForm.tsx`, `Field.tsx`, `widgets/{EnumField,ToggleField,IntField,TextField,GroupField}.tsx`
- Create `frontend/src/components/SchemaForm/useFormState.ts`
- Test: `frontend/src/components/SchemaForm/SchemaForm.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/SchemaForm/SchemaForm.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { SchemaForm } from "./SchemaForm";

const schema = { sections: [{ key: "embedding", label: "Embedding", fields: [
  { key: "provider", dotpath: "embedding.provider", label: "Provider", widget: "enum", options: ["openai", "ollama"] },
  { key: "api_key", dotpath: "embedding.api_key", label: "API key", widget: "text", secret: true },
]}]};

it("renders enum as buttons and batches a single save payload", () => {
  const onSave = vi.fn();
  render(<SchemaForm schema={schema as any}
    values={{ embedding: { provider: "openai", api_key: "********" } }} onSave={onSave} />);
  fireEvent.click(screen.getByRole("button", { name: "ollama" }));   // change enum
  expect(onSave).not.toHaveBeenCalled();                            // not saved yet (batched)
  fireEvent.click(screen.getByRole("button", { name: /save$/i }));  // commit
  expect(onSave).toHaveBeenCalledWith(
    { embedding: { provider: "ollama", api_key: "********" } }, false);
});

it("enum has no free-text input", () => {
  render(<SchemaForm schema={schema as any} values={{ embedding: { provider: "openai" } }} onSave={() => {}} />);
  const providerGroup = screen.getByTestId("field-embedding.provider");
  expect(providerGroup.querySelector("input[type=text]")).toBeNull();
});
```

- [ ] **Step 2: Implement `useFormState`** (holds a draft object, `setValue(dotpath, v)`, `dirty` boolean, `reset`), and `SchemaForm` rendering sections → fields. Widget mapping:
  - `enum` → segmented buttons (one `<button>` per option; selected highlighted). No text input.
  - `toggle` → switch.
  - `int` → number stepper input with `min/max/step`.
  - `text` → text input; if `secret`, type=password + masked placeholder; if `presets`, a dropdown of presets + a "Custom…" entry that reveals the text input only when chosen.
  - `group` → nested fieldset, honoring `visible_when` against the current draft.
  Footer: sticky banner showing "N unsaved changes" with **Discard**, **Save**, **Save + Restart** buttons. Save calls `onSave(draft, false)`; Save+Restart calls `onSave(draft, true)`.

- [ ] **Step 3: Run** → `npx vitest run src/components/SchemaForm` → PASS.
- [ ] **Step 4: Commit** (`feat(dashboard-ui): data-driven SchemaForm with batched save`).

---

### Task 5.5: Config tab (wire SchemaForm to API, validation errors, restart)

**Files:**
- Create `frontend/src/tabs/Config.tsx`
- Test: `frontend/src/tabs/Config.test.tsx`

- [ ] **Step 1: Failing test** — render Config with mocked `getSchema`/`getConfig`/`patchConfig`; assert: changing an enum + clicking Save calls `patchConfig(id, values, false)`; a 422 `{errors:[{field,message}]}` renders inline under the right field; Save+Restart calls with `restart=true` and shows a success toast.

- [ ] **Step 2: Implement** `Config.tsx`: `useQuery` schema + config, feed `SchemaForm`, `useMutation` patchConfig; on 422 map `errors[].field` → inline messages; on success toast + invalidate `["instances"]`.

- [ ] **Step 3: Run** → PASS. **Step 4: Commit** (`feat(dashboard-ui): Config tab with validation + restart`).

---

### Task 5.6: Instances tab (table + row/bulk lifecycle actions)

**Files:**
- Create `frontend/src/tabs/Instances.tsx`, `frontend/src/components/DataTable.tsx`, `ConfirmDialog.tsx`
- Test: `frontend/src/tabs/Instances.test.tsx`

- [ ] **Step 1: Failing test** — render with mocked `listInstances`; assert table shows name/status/port/pid; clicking **Stop** opens ConfirmDialog then calls `stopInstance(id)`; clicking **Start** on a stopped row calls `startInstance(id)`; bulk-select two rows + **Stop selected** calls stop for both.

- [ ] **Step 2: Implement** `DataTable` (generic, click-sortable headers), `ConfirmDialog`, `Instances.tsx` with row actions Start/Stop/Restart/Open(base_url)/Reveal path/**Remove from list** (calls `DELETE /instances/{id}` = forget; confirm) and a bulk action bar. Stopped rows (status `stopped`) show **Start** + **Remove from list**; running rows show Stop/Restart. Add a **Register project** button that POSTs `/instances/register {path}` so a project the dashboard hasn't seen yet can be added. All actions are buttons — no typing except the register path field.

> Stopped instances are listed even with no server running (plan 01 known-store), so the Instances tab and Start action work fleet-wide regardless of which servers are up.

- [ ] **Step 3: Run** → PASS. **Step 4: Commit** (`feat(dashboard-ui): Instances tab with lifecycle actions`).

---

### Task 5.7: Overview tab (fleet summary + charts)

**Files:**
- Create `frontend/src/tabs/Overview.tsx`, `frontend/src/components/StatCard.tsx`, `Charts.tsx`
- Test: `frontend/src/tabs/Overview.test.tsx`

- [ ] **Step 1: Failing test** — mock `listInstances` + per-instance `status`; assert StatCards show counts (running/stopped) and aggregate total chunks; an alert row appears for an `unhealthy` instance.

- [ ] **Step 2: Implement** Overview: cards (running/stopped/unhealthy counts, fleet docs/chunks, aggregate cache hit-rate), a Recharts bar/sparkline of per-instance chunks, alert list. Fan out `status` queries via `useQueries`.

- [ ] **Step 3: Run** → PASS. **Step 4: Commit** (`feat(dashboard-ui): Overview fleet dashboard`).

---

### Task 5.8: Rebuild static + integration smoke

- [ ] Run `cd frontend && npm run build`; commit refreshed `static/`.
- [ ] Manual smoke: `poetry run uvicorn brainpalace_dashboard.app:create_app --factory --port 8787`, open `http://127.0.0.1:8787/dashboard/`, confirm tabs render, an instance's Config loads, a no-op Save works.
- [ ] Commit (`build(dashboard-ui): rebuild static assets`).

---

## Plan 05 self-check
- [ ] Every UISchema widget type renders click-only (enum→buttons, bool→toggle, int→stepper, secret masked, preset+Custom). Vitest proves no free-text on enum.
- [ ] Config edits are batched; one Save / Save+Restart call carries all changes; 422 errors render inline.
- [ ] Instances tab starts/stops/restarts (single + bulk); Overview shows real fleet stats.
- [ ] `task test:dashboard` + frontend `vitest run` green.
