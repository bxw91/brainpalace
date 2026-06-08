import type { ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useRouterState, useNavigate } from "@tanstack/react-router";
import { BrainCircuit, AlertCircle } from "lucide-react";
import { listInstances } from "./api/client";
import { Sidebar } from "./components/Sidebar";
import { InstanceActions } from "./components/InstanceActions";
import { UpdateBanner } from "./components/UpdateBanner";
import { ToastProvider } from "./components/Toast";
import {
  SelectedInstanceProvider,
  useSelectedInstance,
} from "./state/selectedInstance";
import { useLiveInstances } from "./state/useLiveInstances";
import { TABS } from "./router";

export const instancesQuery = {
  queryKey: ["instances"] as const,
  queryFn: listInstances,
};

/**
 * The dashboard has two distinct "pages": the **Server** (control-plane) view
 * and the **Instance** view. The view is the scope of the current route — the
 * left rail switches between them and the tab bar shows ONLY that view's tabs.
 */
export function currentView(pathname: string): "server" | "instance" {
  const onInstanceTab = TABS.some(
    (t) => t.scope === "instance" && t.path !== "/" && pathname.startsWith(t.path),
  );
  return onInstanceTab ? "instance" : "server";
}

function TabBar() {
  const { selectedId } = useSelectedInstance();
  const { location } = useRouterState();
  const current = location.pathname;
  const view = currentView(current);

  // Only the active view's tabs are shown — server and instance are separate
  // pages, not one mixed bar.
  const tabs = TABS.filter((t) =>
    view === "server" ? t.scope === "fleet" : t.scope === "instance",
  );

  return (
    <nav
      id="div-tabbar"
      data-testid="tabbar"
      aria-label="Sections"
      className="flex items-center gap-1 border-b border-line px-6"
    >
      {tabs.map((tab) => {
        const active =
          tab.path === "/"
            ? current === "/" || current === ""
            : current.startsWith(tab.path);
        const disabled = tab.scope === "instance" && !selectedId;
        return (
          <Link
            key={tab.path}
            to={tab.path}
            data-testid={`tab-link-${tab.label.toLowerCase()}`}
            aria-disabled={disabled || undefined}
            disabled={disabled}
            className={[
              "relative -mb-px border-b-2 px-3 py-3 text-sm font-medium transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
              active
                ? "border-accent text-fg"
                : "border-transparent text-fg-muted hover:text-fg",
              disabled ? "pointer-events-none opacity-40" : "",
            ].join(" ")}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}

function ShellInner({ children }: { children: ReactNode }) {
  const { instances, selectedId, setSelectedId, selected } =
    useSelectedInstance();
  const navigate = useNavigate();
  const { location } = useRouterState();
  const view = currentView(location.pathname);

  // Selecting the Server vs an instance switches the whole page (and its tab
  // set) to the default tab of that view.
  // Route types aren't registered (Link uses plain string paths too), so cast
  // the navigate target to satisfy the strict literal union.
  const go = (to: string) => navigate({ to: to as "/" });
  const selectServer = () => go("/");
  const selectInstance = (id: string) => {
    setSelectedId(id);
    go("/status");
  };

  return (
    <div
      id="div-app-root"
      data-testid="app-root"
      className="grid min-h-screen grid-cols-[16rem_1fr]"
    >
      {/* Left rail */}
      <aside className="flex flex-col border-r border-line bg-ink-800/80">
        <div className="flex items-center gap-2.5 px-4 py-5">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-accent/15 text-accent ring-1 ring-inset ring-accent/30">
            <BrainCircuit className="h-5 w-5" aria-hidden="true" />
          </span>
          <span className="min-w-0">
            <span className="block font-display text-sm font-semibold tracking-tight">
              BrainPalace
            </span>
            <span className="block font-mono text-[0.62rem] uppercase tracking-[0.2em] text-fg-faint">
              Control Plane
            </span>
          </span>
        </div>
        <div className="flex-1 overflow-y-auto px-2 pb-4">
          <Sidebar
            instances={instances}
            selectedId={selectedId}
            onSelect={selectInstance}
            view={view}
            onSelectServer={selectServer}
          />
        </div>
      </aside>

      {/* Main column */}
      <div className="flex min-w-0 flex-col">
        <header className="flex items-center justify-between gap-4 px-6 pt-5">
          <div className="min-w-0">
            <p className="eyebrow">{view === "server" ? "Control plane" : "Instance"}</p>
            <h1 className="mt-0.5 truncate font-display text-lg font-semibold tracking-tight">
              {view === "server"
                ? "Server"
                : (selected?.project_root ?? selected?.name ?? "Instance")}
            </h1>
          </div>
          {view === "instance" && selected && (
            <InstanceActions instance={selected} />
          )}
        </header>
        <div className="mt-3">
          <TabBar />
        </div>
        <main className="min-w-0 flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}

/**
 * Wires the global instances query into the selected-instance + toast contexts
 * and renders the chrome. Each route renders inside `children` (the Outlet).
 */
export function AppShell({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  // Single SSE connection feeds the ["instances"] cache. While the stream is
  // live we drop the 5s poll; on SSE error we fall back to polling.
  const { fallback } = useLiveInstances(qc);
  const { data: instances = [], isError } = useQuery({
    ...instancesQuery,
    refetchInterval: fallback ? 5000 : false,
  });

  return (
    <ToastProvider>
      <SelectedInstanceProvider instances={instances}>
        <UpdateBanner />
        {isError && (
          <div
            data-testid="fleet-error"
            role="alert"
            className="flex items-center gap-2 border-b border-bad/30 bg-bad/10 px-6 py-2 text-sm text-bad"
          >
            <AlertCircle className="h-4 w-4" aria-hidden="true" />
            Could not reach the dashboard API.
          </div>
        )}
        <ShellInner>{children}</ShellInner>
      </SelectedInstanceProvider>
    </ToastProvider>
  );
}
