import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Play,
  Square,
  RotateCw,
  Trash2,
  ExternalLink,
  Plus,
  FolderPlus,
} from "lucide-react";
import {
  listInstances,
  startInstance,
  stopInstance,
  restartInstance,
  forgetInstance,
  registerProject,
} from "../api/client";
import type { Instance } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { StatusDot, STATUS_LABEL } from "../components/StatusDot";
import { ErrorState } from "../components/TabState";
import { useToast } from "../components/Toast";

function portOf(baseUrl: string): string {
  if (!baseUrl) return "—";
  try {
    const u = new URL(baseUrl);
    return u.port || (u.protocol === "https:" ? "443" : "80");
  } catch {
    return "—";
  }
}

type PendingAction =
  | { kind: "start"; ids: string[] }
  | { kind: "stop"; ids: string[] }
  | { kind: "restart"; ids: string[] }
  | { kind: "forget"; ids: string[] };

export function Instances() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [registerOpen, setRegisterOpen] = useState(false);
  const [registerPath, setRegisterPath] = useState("");

  // Fleet freshness comes from the single SSE stream (see AppShell /
  // useLiveInstances), which feeds this same ["instances"] cache — so this tab
  // does NOT poll. AppShell keeps a 5s fallback poll only when SSE is down.
  const instancesQ = useQuery({
    queryKey: ["instances"],
    queryFn: listInstances,
  });
  const { data: rows = [], isLoading } = instancesQ;

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["instances"] });

  const lifecycle = useMutation({
    mutationFn: async (action: PendingAction) => {
      const fn =
        action.kind === "start"
          ? startInstance
          : action.kind === "stop"
            ? stopInstance
            : action.kind === "restart"
              ? restartInstance
              : forgetInstance;
      await Promise.all(action.ids.map((id) => fn(id)));
      return action;
    },
    onSuccess: (action) => {
      const verb =
        action.kind === "start"
          ? "Started"
          : action.kind === "stop"
            ? "Stopped"
            : action.kind === "restart"
              ? "Restarted"
              : "Removed";
      toast(
        `${verb} ${action.ids.length} instance${action.ids.length === 1 ? "" : "s"}.`,
        "success",
      );
      setSelected(new Set());
      invalidate();
    },
    onError: (e: unknown) =>
      toast(e instanceof Error ? e.message : "Action failed.", "error"),
  });

  const registerMut = useMutation({
    mutationFn: (path: string) => registerProject(path),
    onSuccess: () => {
      toast("Project registered.", "success");
      setRegisterOpen(false);
      setRegisterPath("");
      invalidate();
    },
    onError: (e: unknown) =>
      toast(e instanceof Error ? e.message : "Could not register.", "error"),
  });

  const toggleSelect = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const selectableRunning = useMemo(
    () => rows.filter((r) => r.status === "running" || r.status === "unhealthy"),
    [rows],
  );
  const allRunningSelected =
    selectableRunning.length > 0 &&
    selectableRunning.every((r) => selected.has(r.id));

  const columns: Column<Instance>[] = [
    {
      key: "name",
      header: "Instance",
      sortValue: (r) => r.name,
      cell: (r) => (
        <div className="flex items-center gap-3">
          <StatusDot id={r.id} status={r.status} />
          <div className="min-w-0">
            <div className="truncate font-medium text-fg">{r.name}</div>
            <div className="truncate font-mono text-[0.68rem] text-fg-faint">
              {r.project_root}
            </div>
          </div>
        </div>
      ),
    },
    {
      key: "status",
      header: "Status",
      sortValue: (r) => r.status,
      cell: (r) => (
        <span className="font-mono text-xs text-fg-muted">
          {STATUS_LABEL[r.status]}
        </span>
      ),
    },
    {
      key: "port",
      header: "Port",
      align: "right",
      sortValue: (r) => Number(portOf(r.base_url)) || 0,
      cell: (r) => (
        <span className="font-mono text-xs tabular-nums text-fg-muted">
          {portOf(r.base_url)}
        </span>
      ),
    },
    {
      key: "pid",
      header: "PID",
      align: "right",
      sortValue: (r) => r.pid ?? 0,
      cell: (r) => (
        <span className="font-mono text-xs tabular-nums text-fg-muted">
          {r.pid ?? "—"}
        </span>
      ),
    },
  ];

  const isStopped = (s: Instance["status"]) =>
    s === "stopped" || s === "stale";

  const confirmCopy = (a: PendingAction): { title: string; msg: string; label: string } => {
    const n = a.ids.length;
    const noun = n === 1 ? "this instance" : `${n} instances`;
    if (a.kind === "start")
      return { title: "Start instance", msg: `Start ${noun}?`, label: "Start" };
    if (a.kind === "stop")
      return { title: "Stop instance", msg: `Stop ${noun}? In-flight queries will be interrupted.`, label: "Stop" };
    if (a.kind === "restart")
      return { title: "Restart instance", msg: `Restart ${noun}?`, label: "Restart" };
    return {
      title: "Remove from list",
      msg: `Remove ${noun} from the dashboard? This forgets the project — it does not delete any index data.`,
      label: "Remove",
    };
  };

  return (
    <div data-testid="tab-instances" className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="eyebrow">Fleet</p>
          <h2 className="mt-0.5 font-display text-lg font-semibold tracking-tight">
            {rows.length} instance{rows.length === 1 ? "" : "s"}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          {selected.size > 0 && (
            <button
              type="button"
              data-testid="btn-bulk-stop"
              onClick={() =>
                setPending({ kind: "stop", ids: [...selected] })
              }
              className="btn-danger btn-sm"
            >
              <Square className="h-3.5 w-3.5" aria-hidden="true" />
              Stop selected ({selected.size})
            </button>
          )}
          <button
            type="button"
            data-testid="btn-register-open"
            onClick={() => setRegisterOpen(true)}
            className="btn-primary btn-sm"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            Register project
          </button>
        </div>
      </div>

      {instancesQ.isError ? (
        <ErrorState
          testId="instances-error"
          message={(instancesQ.error as Error)?.message}
          onRetry={() => instancesQ.refetch()}
          retrying={instancesQ.isFetching}
        />
      ) : isLoading ? (
        <div className="panel p-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton mb-2 h-12 last:mb-0" />
          ))}
        </div>
      ) : (
        <DataTable
          rows={rows}
          columns={columns}
          rowKey={(r) => r.id}
          rowTestId={(r) => `row-${r.id}`}
          empty="No instances registered. Use “Register project” to add one."
          leading={{
            header: (
              <input
                type="checkbox"
                aria-label="Select all running"
                data-testid="select-all"
                checked={allRunningSelected}
                onChange={() =>
                  setSelected(
                    allRunningSelected
                      ? new Set()
                      : new Set(selectableRunning.map((r) => r.id)),
                  )
                }
                className="h-4 w-4 cursor-pointer accent-accent"
              />
            ),
            cell: (r) =>
              isStopped(r.status) ? null : (
                <input
                  type="checkbox"
                  aria-label={`Select ${r.name}`}
                  data-testid={`select-${r.id}`}
                  checked={selected.has(r.id)}
                  onChange={() => toggleSelect(r.id)}
                  className="h-4 w-4 cursor-pointer accent-accent"
                />
              ),
          }}
          trailing={{
            header: "Actions",
            cell: (r) => (
              <div className="flex items-center justify-end gap-1.5">
                {isStopped(r.status) ? (
                  <>
                    <button
                      type="button"
                      data-testid={`btn-start-${r.id}`}
                      onClick={() => setPending({ kind: "start", ids: [r.id] })}
                      className="btn-ghost btn-sm"
                      title="Start"
                    >
                      <Play className="h-3.5 w-3.5" aria-hidden="true" />
                      Start
                    </button>
                    <button
                      type="button"
                      data-testid={`btn-forget-${r.id}`}
                      onClick={() => setPending({ kind: "forget", ids: [r.id] })}
                      className="btn-ghost btn-sm"
                      title="Remove from list"
                      aria-label={`Remove ${r.name} from list`}
                    >
                      <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                    </button>
                  </>
                ) : (
                  <>
                    {r.base_url && (
                      <a
                        href={r.base_url}
                        target="_blank"
                        rel="noreferrer"
                        data-testid={`btn-open-${r.id}`}
                        className="btn-ghost btn-sm"
                        title="Open server"
                        aria-label={`Open ${r.name}`}
                      >
                        <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                      </a>
                    )}
                    <button
                      type="button"
                      data-testid={`btn-restart-${r.id}`}
                      onClick={() =>
                        setPending({ kind: "restart", ids: [r.id] })
                      }
                      className="btn-ghost btn-sm"
                      title="Restart"
                      aria-label={`Restart ${r.name}`}
                    >
                      <RotateCw className="h-3.5 w-3.5" aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      data-testid={`btn-stop-${r.id}`}
                      onClick={() => setPending({ kind: "stop", ids: [r.id] })}
                      className="btn-danger btn-sm"
                      title="Stop"
                    >
                      <Square className="h-3.5 w-3.5" aria-hidden="true" />
                      Stop
                    </button>
                  </>
                )}
              </div>
            ),
          }}
        />
      )}

      <ConfirmDialog
        open={!!pending}
        title={pending ? confirmCopy(pending).title : ""}
        message={pending ? confirmCopy(pending).msg : ""}
        confirmLabel={pending ? confirmCopy(pending).label : "Confirm"}
        tone={
          pending?.kind === "restart" || pending?.kind === "start"
            ? "default"
            : "danger"
        }
        busy={lifecycle.isPending}
        onCancel={() => setPending(null)}
        onConfirm={() => {
          if (pending) lifecycle.mutate(pending);
          setPending(null);
        }}
      />

      {registerOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center p-4">
          <div
            className="absolute inset-0 bg-ink-900/70 backdrop-blur-sm"
            onClick={() => setRegisterOpen(false)}
            aria-hidden="true"
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="h2-register-title"
            data-testid="register-dialog"
            className="panel animate-fade-up relative z-10 w-full max-w-md p-6"
          >
            <div className="flex items-start gap-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-accent/15 text-accent">
                <FolderPlus className="h-5 w-5" aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <h2
                  id="h2-register-title"
                  className="font-display text-base font-semibold tracking-tight"
                >
                  Register project
                </h2>
                <p className="mt-1 text-sm text-fg-muted">
                  Absolute path to a project containing a{" "}
                  <code className="font-mono text-fg-faint">.brainpalace/</code>{" "}
                  directory.
                </p>
              </div>
            </div>
            <div className="mt-4">
              <label
                htmlFor="input-register-path"
                className="mb-1.5 block text-xs font-medium text-fg-muted"
              >
                Project path
              </label>
              <input
                id="input-register-path"
                data-testid="input-register-path"
                type="text"
                value={registerPath}
                placeholder="/home/you/code/my-project"
                onChange={(e) => setRegisterPath(e.target.value)}
                className="w-full rounded-lg border border-line bg-ink-900/50 px-3 py-2 font-mono text-sm text-fg outline-none transition-colors placeholder:text-fg-faint focus:border-accent/50 focus:ring-2 focus:ring-accent/30"
              />
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setRegisterOpen(false)}
                className="btn-ghost btn-sm"
              >
                Cancel
              </button>
              <button
                type="button"
                data-testid="btn-register-submit"
                disabled={!registerPath.trim() || registerMut.isPending}
                onClick={() => registerMut.mutate(registerPath.trim())}
                className="btn-primary btn-sm"
              >
                Register
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
