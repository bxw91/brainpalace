/** Spec-side access to the sandbox metadata written by global-setup. */
import { readFileSync } from "node:fs";
import { STATE_FILE } from "./paths";

export type E2EState = {
  pid: number;
  baseURL: string;
  sandbox: string;
  projectRoot: string;
  indexDir: string;
  projectName: string;
};

export function readState(): E2EState {
  return JSON.parse(readFileSync(STATE_FILE, "utf-8")) as E2EState;
}

/**
 * True when the sandbox cannot launch a real browser and the browser-driven
 * specs must be skipped (set `BROWSER_UNAVAILABLE=1`). Everything else (config,
 * fixtures, setup) stays correct and runnable elsewhere.
 */
export const BROWSER_UNAVAILABLE =
  process.env.BROWSER_UNAVAILABLE === "1" ||
  process.env.BROWSER_UNAVAILABLE === "true";
