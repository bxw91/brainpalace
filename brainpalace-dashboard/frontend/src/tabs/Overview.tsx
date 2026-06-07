import { useMemo } from "react";
import { useQuery, useQueries } from "@tanstack/react-query";
import {
  Activity,
  PauseCircle,
  AlertTriangle,
  FileText,
  Boxes,
  ServerCog,
} from "lucide-react";
import { listInstances, getInstanceStatus } from "../api/client";
import type { InstanceStatusPayload } from "../api/types";
import { StatCard } from "../components/StatCard";
import { ChunkBarChart, type ChunkDatum } from "../components/Charts";
import { StatusDot, STATUS_LABEL } from "../components/StatusDot";
import { ErrorState } from "../components/TabState";

const fmt = (n: number) => n.toLocaleString("en-US");

export function Overview() {
  // Fleet freshness comes from the single SSE stream (see AppShell /
  // useLiveInstances), which pushes into this same ["instances"] cache — so this
  // tab does NOT poll. AppShell keeps a 5s fallback poll only when SSE is down.
  const instancesQ = useQuery({
    queryKey: ["instances"],
    queryFn: listInstances,
  });
  const { data: instances = [], isLoading } = instancesQ;

  // Only running/unhealthy instances have a reachable status endpoint.
  const live = instances.filter(
    (i) => i.status === "running" || i.status === "unhealthy",
  );

  const statusQueries = useQueries({
    queries: live.map((i) => ({
      queryKey: ["status", i.id],
      queryFn: () => getInstanceStatus(i.id),
      retry: false,
      refetchInterval: 8000,
    })),
  });

  const statusById = useMemo(() => {
    const m = new Map<string, InstanceStatusPayload>();
    live.forEach((i, idx) => {
      const data = statusQueries[idx]?.data;
      if (data) m.set(i.id, data);
    });
    return m;
  }, [live, statusQueries]);

  const counts = {
    running: instances.filter((i) => i.status === "running").length,
    stopped: instances.filter((i) => i.status === "stopped").length,
    unhealthy: instances.filter((i) => i.status === "unhealthy").length,
    stale: instances.filter((i) => i.status === "stale").length,
  };

  const totalChunks = [...statusById.values()].reduce(
    (sum, s) => sum + (s.total_chunks ?? 0),
    0,
  );
  const totalDocs = [...statusById.values()].reduce(
    (sum, s) => sum + (s.total_documents ?? 0),
    0,
  );

  const chartData: ChunkDatum[] = live.map((i) => ({
    name: i.name,
    chunks: statusById.get(i.id)?.total_chunks ?? 0,
    reachable: statusById.has(i.id),
  }));

  const alerts = instances.filter(
    (i) => i.status === "unhealthy" || i.status === "stale",
  );

  const statsLoading =
    isLoading ||
    (live.length > 0 && statusQueries.some((q) => q.isLoading));

  if (instancesQ.isError) {
    return (
      <div data-testid="tab-overview">
        <ErrorState
          testId="overview-error"
          message={(instancesQ.error as Error)?.message}
          onRetry={() => instancesQ.refetch()}
          retrying={instancesQ.isFetching}
        />
      </div>
    );
  }

  if (!isLoading && instances.length === 0) {
    return (
      <div
        data-testid="tab-overview"
        className="grid min-h-[60vh] place-items-center"
      >
        <div
          data-testid="overview-empty"
          className="panel max-w-md p-10 text-center"
        >
          <ServerCog
            className="mx-auto mb-4 h-8 w-8 text-fg-faint"
            aria-hidden="true"
          />
          <h2 className="font-display text-base font-semibold tracking-tight">
            No instances yet
          </h2>
          <p className="mt-2 text-sm text-fg-muted">
            Run{" "}
            <code className="rounded bg-ink-900/60 px-1.5 py-0.5 font-mono text-fg-faint">
              brainpalace start
            </code>{" "}
            in a project, or register one from the Instances tab.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="tab-overview" className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <StatCard
          testId="stat-running"
          label="Running"
          value={counts.running}
          tone="run"
          icon={<Activity className="h-4 w-4" aria-hidden="true" />}
        />
        <StatCard
          testId="stat-stopped"
          label="Stopped"
          value={counts.stopped}
          tone="idle"
          icon={<PauseCircle className="h-4 w-4" aria-hidden="true" />}
        />
        <StatCard
          testId="stat-unhealthy"
          label="Unhealthy"
          value={counts.unhealthy + counts.stale}
          tone={counts.unhealthy + counts.stale > 0 ? "bad" : "idle"}
          icon={<AlertTriangle className="h-4 w-4" aria-hidden="true" />}
        />
        <StatCard
          testId="stat-docs"
          label="Fleet documents"
          value={fmt(totalDocs)}
          tone="accent"
          loading={statsLoading}
          icon={<FileText className="h-4 w-4" aria-hidden="true" />}
        />
        <StatCard
          testId="stat-chunks"
          label="Fleet chunks"
          value={fmt(totalChunks)}
          tone="accent"
          loading={statsLoading}
          icon={<Boxes className="h-4 w-4" aria-hidden="true" />}
        />
      </div>

      {alerts.length > 0 && (
        <div
          data-testid="alerts"
          role="region"
          aria-label="Alerts"
          className="panel border-bad/30 p-4"
        >
          <p className="eyebrow mb-3 text-bad">Attention needed</p>
          <ul className="flex flex-col gap-2">
            {alerts.map((i) => (
              <li
                key={i.id}
                data-testid={`alert-${i.id}`}
                className="flex items-center gap-3 rounded-lg bg-bad/5 px-3 py-2.5"
              >
                <StatusDot id={`alert-${i.id}`} status={i.status} />
                <span className="font-medium text-fg">{i.name}</span>
                <span className="font-mono text-xs text-fg-faint">
                  {i.project_root}
                </span>
                <span className="ml-auto font-mono text-xs text-bad">
                  {STATUS_LABEL[i.status]}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="panel p-6">
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="font-display text-base font-semibold tracking-tight">
            Chunks by instance
          </h2>
          <span className="font-mono text-[0.68rem] uppercase tracking-[0.18em] text-fg-faint">
            {live.length} live
          </span>
        </div>
        {statsLoading ? (
          <div className="flex flex-col gap-2">
            {[0, 1, 2].map((i) => (
              <div key={i} className="skeleton h-7" />
            ))}
          </div>
        ) : (
          <ChunkBarChart data={chartData} />
        )}
      </div>
    </div>
  );
}
