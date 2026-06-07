import {
  createRootRoute,
  createRoute,
  createRouter,
  createBrowserHistory,
  Outlet,
} from "@tanstack/react-router";
import { AppShell } from "./app";
import { Overview } from "./tabs/Overview";
import { Instances } from "./tabs/Instances";
import { Settings } from "./tabs/Settings";
import { GlobalConfig } from "./tabs/GlobalConfig";
import { Status } from "./tabs/Status";
import { Config } from "./tabs/Config";
import { Runtime } from "./tabs/Runtime";
import { Folders } from "./tabs/Folders";
import { Queries } from "./tabs/Queries";
import { Jobs } from "./tabs/Jobs";
import { Cache } from "./tabs/Cache";
import { Graph } from "./tabs/Graph";
import { Sessions } from "./tabs/Sessions";
import { Logs } from "./tabs/Logs";

/**
 * Tab registry. The shell renders the top tab-bar from this list. `scope:
 * "instance"` tabs require a selected instance (auto-disabled otherwise).
 */
export type TabDef = {
  path: string;
  label: string;
  scope: "fleet" | "instance";
};

export const TABS: TabDef[] = [
  { path: "/", label: "Overview", scope: "fleet" },
  { path: "/instances", label: "Instances", scope: "fleet" },
  { path: "/global-config", label: "Global config", scope: "fleet" },
  { path: "/settings", label: "Settings", scope: "fleet" },
  { path: "/status", label: "Status", scope: "instance" },
  { path: "/config", label: "Config", scope: "instance" },
  { path: "/runtime", label: "Runtime", scope: "instance" },
  { path: "/folders", label: "Folders", scope: "instance" },
  { path: "/queries", label: "Queries", scope: "instance" },
  { path: "/jobs", label: "Jobs", scope: "instance" },
  { path: "/cache", label: "Cache", scope: "instance" },
  { path: "/graph", label: "Graph", scope: "instance" },
  { path: "/sessions", label: "Sessions", scope: "instance" },
  { path: "/logs", label: "Logs", scope: "instance" },
];

const rootRoute = createRootRoute({
  component: () => (
    <AppShell>
      <Outlet />
    </AppShell>
  ),
});

// Tabs accept an optional `instanceId` prop (for testability); the router never
// passes one, so they resolve the selected instance from context at runtime.
const make = (path: string, component: () => JSX.Element) =>
  createRoute({ getParentRoute: () => rootRoute, path, component });

const overviewRoute = make("/", () => <Overview />);
const instancesRoute = make("/instances", () => <Instances />);
const globalConfigRoute = make("/global-config", () => <GlobalConfig />);
const settingsRoute = make("/settings", () => <Settings />);
const statusRoute = make("/status", () => <Status />);
const configRoute = make("/config", () => <Config />);
const runtimeRoute = make("/runtime", () => <Runtime />);
const foldersRoute = make("/folders", () => <Folders />);
const queriesRoute = make("/queries", () => <Queries />);
const jobsRoute = make("/jobs", () => <Jobs />);
const cacheRoute = make("/cache", () => <Cache />);
const graphRoute = make("/graph", () => <Graph />);
const sessionsRoute = make("/sessions", () => <Sessions />);
const logsRoute = make("/logs", () => <Logs />);

const routeTree = rootRoute.addChildren([
  overviewRoute,
  instancesRoute,
  globalConfigRoute,
  settingsRoute,
  statusRoute,
  configRoute,
  runtimeRoute,
  foldersRoute,
  queriesRoute,
  jobsRoute,
  cacheRoute,
  graphRoute,
  sessionsRoute,
  logsRoute,
]);

export const router = createRouter({
  routeTree,
  history: createBrowserHistory(),
  basepath: "/dashboard",
  defaultPreload: "intent",
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
