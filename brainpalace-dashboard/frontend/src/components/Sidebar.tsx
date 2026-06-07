import { ServerCog, Boxes } from "lucide-react";
import type { Instance } from "../api/types";
import { StatusDot, STATUS_LABEL } from "./StatusDot";

export function Sidebar({
  instances,
  selectedId,
  onSelect,
  view = "server",
  onSelectServer,
  loading = false,
}: {
  instances: Instance[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  view?: "server" | "instance";
  onSelectServer?: () => void;
  loading?: boolean;
}) {
  return (
    <nav
      id="div-sidebar-instances"
      data-testid="sidebar-instances"
      aria-label="Navigation"
      className="flex flex-col gap-1"
    >
      {/* Control plane (server) — its own page, separate from any instance. */}
      <p className="eyebrow px-3 pb-2 pt-1">Control plane</p>
      <button
        type="button"
        data-testid="nav-server"
        aria-current={view === "server" ? "true" : undefined}
        onClick={onSelectServer}
        className={[
          "group mb-2 flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-all duration-150",
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
          view === "server"
            ? "bg-ink-600/80 ring-1 ring-inset ring-line-strong"
            : "hover:bg-ink-700/60",
        ].join(" ")}
      >
        <span className="grid h-6 w-6 place-items-center rounded-md bg-accent/15 text-accent">
          <Boxes className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-fg">Server</span>
          <span className="block truncate font-mono text-[0.68rem] text-fg-faint">
            overview · instances · global config · settings
          </span>
        </span>
        {view === "server" && (
          <span aria-hidden="true" className="h-6 w-0.5 rounded-full bg-accent" />
        )}
      </button>

      <p className="eyebrow px-3 pb-2 pt-1">Instances</p>

      {loading && instances.length === 0 ? (
        <div className="flex flex-col gap-1" data-testid="sidebar-loading">
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton mx-1 h-12 rounded-lg" />
          ))}
        </div>
      ) : instances.length === 0 ? (
        <div
          id="div-sidebar-empty"
          data-testid="sidebar-empty"
          className="mx-1 mt-2 rounded-lg border border-dashed border-line px-3 py-6 text-center"
        >
          <ServerCog
            className="mx-auto mb-2 h-5 w-5 text-fg-faint"
            aria-hidden="true"
          />
          <p className="text-xs text-fg-muted">No instances yet</p>
          <p className="mt-1 text-[0.7rem] text-fg-faint">
            Register a project from the Instances tab.
          </p>
        </div>
      ) : (
        <ul className="flex flex-col gap-0.5">
          {instances.map((it) => {
            const active = view === "instance" && it.id === selectedId;
            return (
              <li key={it.id}>
                <button
                  type="button"
                  id={`btn-instance-${it.id}`}
                  data-testid={`instance-row-${it.id}`}
                  aria-current={active ? "true" : undefined}
                  onClick={() => onSelect(it.id)}
                  className={[
                    "group flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-all duration-150",
                    "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
                    active
                      ? "bg-ink-600/80 ring-1 ring-inset ring-line-strong"
                      : "hover:bg-ink-700/60",
                  ].join(" ")}
                >
                  <StatusDot id={it.id} status={it.status} />
                  <span className="min-w-0 flex-1">
                    <span
                      className={[
                        "block truncate text-sm font-medium",
                        active ? "text-fg" : "text-fg group-hover:text-fg",
                      ].join(" ")}
                    >
                      {it.name}
                    </span>
                    <span className="block truncate font-mono text-[0.68rem] text-fg-faint">
                      {STATUS_LABEL[it.status]}
                      {it.mode ? ` · ${it.mode}` : ""}
                    </span>
                  </span>
                  {active && (
                    <span
                      aria-hidden="true"
                      className="h-6 w-0.5 rounded-full bg-accent"
                    />
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </nav>
  );
}
