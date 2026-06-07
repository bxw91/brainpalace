/**
 * Throwaway-project + isolated-state helpers for the dashboard E2E suite.
 *
 * The dashboard and the project servers it spawns read their durable state from
 * the XDG state dir and per-project `.brainpalace/` directories. To keep the E2E
 * run hermetic — never touching the developer's real fleet — we point
 * `XDG_STATE_HOME` / `XDG_CONFIG_HOME` at a scratch dir and seed exactly one
 * project there.
 */
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export type E2EProject = {
  /** Root of the scratch sandbox (everything below lives here). */
  sandbox: string;
  /** Isolated XDG_STATE_HOME for the dashboard + spawned servers. */
  xdgState: string;
  /** Isolated XDG_CONFIG_HOME (dashboard config lives here). */
  xdgConfig: string;
  /** The seeded project's root directory. */
  projectRoot: string;
  /** The seeded project's `.brainpalace/` state dir. */
  stateDir: string;
  /** A small folder with content to index (contains the word "hello"). */
  indexDir: string;
  /** Human-friendly project name (matches the folder name). */
  projectName: string;
};

/**
 * The provider config the seeded project boots with. OpenAI embeddings make the
 * index + query steps of the headline flow real (an `OPENAI_API_KEY` must be in
 * the environment). Summarization also uses OpenAI so the suite needs only one
 * key.
 */
// Only top-level keys accepted by config_schema.validate_config_dict — the
// dashboard re-validates the whole file on save, so any extra key (e.g.
// session_indexing) would make the Save+Restart step fail validation.
const CONFIG_YAML = `embedding:
  provider: openai
  model: text-embedding-3-small
  api_key_env: OPENAI_API_KEY
summarization:
  provider: openai
  model: gpt-4o-mini
  api_key_env: OPENAI_API_KEY
graphrag:
  enabled: false
query_log:
  enabled: true
  retention_days: 7
`;

/** Runtime config (`config.json`): bind host + auto-port scan range. */
function configJson(projectRoot: string): string {
  return JSON.stringify(
    {
      bind_host: "127.0.0.1",
      port_range_start: 8810,
      port_range_end: 8870,
      auto_port: true,
      chunk_size: 512,
      chunk_overlap: 50,
      exclude_patterns: [
        "**/node_modules/**",
        "**/__pycache__/**",
        "**/.git/**",
      ],
      project_root: projectRoot,
    },
    null,
    2,
  );
}

/** A tiny source file whose content the headline query ("hello") will match. */
const SAMPLE_SOURCE = `// itest sample module — indexed by the dashboard E2E suite.
export function greet(name) {
  // say hello to the caller; this token is what the E2E query searches for.
  return "hello " + name;
}

export function farewell(name) {
  return "goodbye " + name;
}
`;

/**
 * Create the scratch sandbox: isolated XDG dirs, one seeded project named
 * "itest" with a bootable config, an index folder, and a registration entry in
 * the dashboard's known-projects store so the instance shows up immediately.
 */
export function createSandbox(): E2EProject {
  const sandbox = mkdtempSync(join(tmpdir(), "bp-dash-e2e-"));
  const xdgState = join(sandbox, "xdg-state");
  const xdgConfig = join(sandbox, "xdg-config");
  const projectName = "itest";
  const projectRoot = join(sandbox, projectName);
  const stateDir = join(projectRoot, ".brainpalace");
  const indexDir = join(projectRoot, "src");

  for (const d of [xdgState, xdgConfig, stateDir, indexDir]) {
    mkdirSync(d, { recursive: true });
  }

  writeFileSync(join(stateDir, "config.yaml"), CONFIG_YAML);
  writeFileSync(join(stateDir, "config.json"), configJson(projectRoot));
  writeFileSync(join(indexDir, "greeting.js"), SAMPLE_SOURCE);

  // Seed the dashboard's durable known-projects store so the project lists
  // immediately as a stopped, Start-able instance. The store lives under
  // <XDG_STATE>/brainpalace/dashboard_known.json (xdg_paths nests "brainpalace").
  const brainpalaceState = join(xdgState, "brainpalace");
  mkdirSync(brainpalaceState, { recursive: true });
  writeFileSync(
    join(brainpalaceState, "dashboard_known.json"),
    JSON.stringify(
      {
        [projectRoot]: { state_dir: stateDir, project_name: projectName },
      },
      null,
      2,
    ),
  );

  return {
    sandbox,
    xdgState,
    xdgConfig,
    projectRoot,
    stateDir,
    indexDir,
    projectName,
  };
}

/** The environment overrides every dashboard/server process in the run needs. */
export function sandboxEnv(p: E2EProject): NodeJS.ProcessEnv {
  return {
    ...process.env,
    XDG_STATE_HOME: p.xdgState,
    XDG_CONFIG_HOME: p.xdgConfig,
    PYTHON_KEYRING_BACKEND: "keyring.backends.null.Keyring",
    // Keep the run hermetic: no transcript archiving / session indexing / git
    // history walk for the throwaway project.
    SESSION_ARCHIVE_ENABLED: "false",
    SESSION_INDEXING_ENABLED: "false",
  };
}
