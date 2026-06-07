/** Shared filesystem locations + the well-known E2E port. */
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));

/** Repo root (…/e2e/dashboard/fixtures → up 3). */
export const REPO_ROOT = resolve(here, "..", "..", "..");

/** The dashboard Poetry package (holds the venv + built static SPA). */
export const DASHBOARD_DIR = resolve(REPO_ROOT, "brainpalace-dashboard");

/** The built SPA served by the dashboard (`npm run build` output). */
export const STATIC_DIR = resolve(
  DASHBOARD_DIR,
  "brainpalace_dashboard",
  "static",
);

/** Fixed port for the E2E dashboard (outside the project-server scan range). */
export const DASHBOARD_PORT = 8799;

/** Base URL the SPA is served from. */
export const BASE_URL = `http://127.0.0.1:${DASHBOARD_PORT}/dashboard/`;

/** Where global-setup stashes sandbox metadata for teardown + specs. */
export const STATE_FILE = resolve(here, "..", ".e2e-tmp", "state.json");
