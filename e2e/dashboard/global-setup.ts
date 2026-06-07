/**
 * Playwright global setup: stand up a real control plane against a hermetic
 * sandbox, then hand specs a `baseURL` plus the seeded index dir.
 *
 * Steps:
 *   1. Create the scratch sandbox (isolated XDG dirs + one seeded "itest"
 *      project, pre-registered in the dashboard's known-projects store).
 *   2. Launch the dashboard via the dashboard venv's `uvicorn` (which imports
 *      the editable worktree server, so spawned project servers have the
 *      Phase-04 endpoints), serving the freshly built SPA.
 *   3. Wait for `/dashboard/api/health`.
 *   4. Persist sandbox + pid metadata for the specs and global-teardown.
 *
 * If the SPA build is missing, setup fails loudly with the exact command to run
 * — the headline flow drives the UI, so a build is mandatory.
 */
import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import type { FullConfig } from "@playwright/test";

import { createSandbox, sandboxEnv, type E2EProject } from "./fixtures/project";
import {
  BASE_URL,
  DASHBOARD_DIR,
  DASHBOARD_PORT,
  STATE_FILE,
  STATIC_DIR,
} from "./fixtures/paths";

const HEALTH_URL = `http://127.0.0.1:${DASHBOARD_PORT}/dashboard/api/health`;

function venvPython(): string {
  // Resolve the dashboard Poetry venv interpreter (has editable server + uvicorn).
  const venvDir = execFileSync("poetry", ["env", "info", "-p"], {
    cwd: DASHBOARD_DIR,
    env: {
      ...process.env,
      PYTHON_KEYRING_BACKEND: "keyring.backends.null.Keyring",
    },
    encoding: "utf-8",
  }).trim();
  const py = join(venvDir, "bin", "python");
  if (!venvDir || !existsSync(py)) {
    throw new Error(
      `Could not resolve the dashboard venv python (got "${py}"). ` +
        `Run: cd brainpalace-dashboard && poetry install`,
    );
  }
  return py;
}

async function waitForHealth(timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastErr = "";
  while (Date.now() < deadline) {
    try {
      const r = await fetch(HEALTH_URL);
      if (r.ok) return;
      lastErr = `status ${r.status}`;
    } catch (e) {
      lastErr = e instanceof Error ? e.message : String(e);
    }
    await new Promise((res) => setTimeout(res, 300));
  }
  throw new Error(`Dashboard never became healthy at ${HEALTH_URL}: ${lastErr}`);
}

export default async function globalSetup(_config: FullConfig): Promise<void> {
  if (!existsSync(`${STATIC_DIR}/index.html`)) {
    throw new Error(
      `Built SPA not found at ${STATIC_DIR}/index.html.\n` +
        `Build it first: cd brainpalace-dashboard/frontend && npm run build`,
    );
  }

  const project: E2EProject = createSandbox();
  const py = venvPython();

  const env = {
    ...sandboxEnv(project),
    BRAINPALACE_DASHBOARD_STATIC: STATIC_DIR,
  };

  const child: ChildProcess = spawn(
    py,
    [
      "-m",
      "uvicorn",
      "brainpalace_dashboard.app:create_app",
      "--factory",
      "--host",
      "127.0.0.1",
      "--port",
      String(DASHBOARD_PORT),
    ],
    { cwd: DASHBOARD_DIR, env, stdio: "inherit" },
  );

  if (!child.pid) {
    throw new Error("Failed to spawn the dashboard process (no pid).");
  }

  try {
    await waitForHealth(30_000);
  } catch (err) {
    try {
      process.kill(child.pid, "SIGTERM");
    } catch {
      /* already gone */
    }
    throw err;
  }

  mkdirSync(dirname(STATE_FILE), { recursive: true });
  writeFileSync(
    STATE_FILE,
    JSON.stringify(
      {
        pid: child.pid,
        baseURL: BASE_URL,
        sandbox: project.sandbox,
        projectRoot: project.projectRoot,
        indexDir: project.indexDir,
        projectName: project.projectName,
      },
      null,
      2,
    ),
  );
}
