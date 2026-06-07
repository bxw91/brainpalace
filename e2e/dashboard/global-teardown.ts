/**
 * Playwright global teardown: stop the dashboard, kill any project server it
 * spawned, and delete the scratch sandbox. Best-effort throughout — a failed
 * teardown must never mask a test result.
 */
import { existsSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { STATE_FILE } from "./fixtures/paths";

type State = {
  pid: number;
  sandbox: string;
  projectRoot: string;
};

function killTree(pid: number): void {
  try {
    // Negative pid would target a group; we spawned without a new session, so
    // just signal the process. uvicorn's reloader is off, so this is the server.
    process.kill(pid, "SIGTERM");
  } catch {
    /* already gone */
  }
}

/** Read a project server's runtime pid from its sandboxed `.brainpalace`. */
function projectServerPid(state: State): number | null {
  const runtime = join(state.projectRoot, ".brainpalace", "runtime.json");
  if (!existsSync(runtime)) return null;
  try {
    const data = JSON.parse(readFileSync(runtime, "utf-8")) as { pid?: number };
    return typeof data.pid === "number" ? data.pid : null;
  } catch {
    return null;
  }
}

export default async function globalTeardown(): Promise<void> {
  if (!existsSync(STATE_FILE)) return;

  let state: State;
  try {
    state = JSON.parse(readFileSync(STATE_FILE, "utf-8")) as State;
  } catch {
    return;
  }

  // 1) Stop any project server the dashboard spawned (it survives in the sandbox).
  const serverPid = projectServerPid(state);
  if (serverPid) killTree(serverPid);

  // 2) Stop the dashboard process.
  if (state.pid) killTree(state.pid);

  // Give processes a moment to exit before removing their files.
  await new Promise((res) => setTimeout(res, 800));

  // 3) Remove the scratch sandbox.
  if (state.sandbox && existsSync(state.sandbox)) {
    try {
      rmSync(state.sandbox, { recursive: true, force: true });
    } catch {
      /* leave it for the OS tmp reaper */
    }
  }

  try {
    rmSync(STATE_FILE, { force: true });
  } catch {
    /* ignore */
  }
}
