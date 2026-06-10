import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Database, Trash2, Target, XCircle, HardDrive } from "lucide-react";
import { getCache, getCacheHistory, clearCache } from "../api/client";
import { StatCard } from "../components/StatCard";
import { RateChart } from "../components/Charts";
import { CacheEconomicsPanel } from "../components/CacheEconomics";
import { HitRateGauge } from "../components/HitRateGauge";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";
import { useOptionalSelectedInstance } from "../state/selectedInstance";
import {
  NoInstance,
  StoppedState,
  ErrorState,
  TabSkeleton,
  isUnreachable,
} from "../components/TabState";

const fmt = (n: number) => n.toLocaleString("en-US");

function fmtBytes(b: number): string {
  if (b < 1024) return `${b} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = b / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(1)} ${units[i]}`;
}

export function Cache({ instanceId }: { instanceId?: string }) {
  const ctx = useOptionalSelectedInstance();
  const id = instanceId ?? ctx?.selectedId ?? null;
  const { toast } = useToast();
  const qc = useQueryClient();
  const [clearOpen, setClearOpen] = useState(false);

  // 60s polling drives the server's opportunistic stats_history snapshots
  // (GET /index/cache/ calls maybe_snapshot; the 5-min server throttle
  // bounds the write rate).
  const cacheQ = useQuery({
    queryKey: ["cache", id],
    queryFn: () => getCache(id!),
    enabled: !!id,
    retry: false,
    refetchInterval: 60_000,
  });

  const historyQ = useQuery({
    queryKey: ["cache-history", id],
    queryFn: () => getCacheHistory(id!),
    enabled: !!id,
    retry: false,
    refetchInterval: 60_000,
  });

  const trend = (historyQ.data?.snapshots ?? []).map((s) => {
    const total = s.hits + s.misses;
    const d = new Date(s.ts * 1000);
    return {
      label: `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, "0")}`,
      value: total > 0 ? Math.round((s.hits / total) * 100) : 0,
    };
  });

  const clearM = useMutation({
    mutationFn: () => clearCache(id!),
    onSuccess: () => {
      setClearOpen(false);
      toast("Embedding cache cleared.", "success");
      qc.invalidateQueries({ queryKey: ["cache", id] });
      qc.invalidateQueries({ queryKey: ["status", id] });
      qc.invalidateQueries({ queryKey: ["cache-history", id] });
      qc.invalidateQueries({ queryKey: ["cache-economics", id] });
    },
    onError: (e: unknown) =>
      toast(e instanceof Error ? e.message : "Failed to clear cache.", "error"),
  });

  if (!id) {
    return <NoInstance testId="tab-cache" message="Select an instance to inspect its embedding cache." />;
  }
  if (isUnreachable(cacheQ.error)) {
    return <StoppedState testId="cache-stopped" />;
  }
  if (cacheQ.isError) {
    return (
      <ErrorState
        testId="cache-error"
        message={(cacheQ.error as Error)?.message}
        onRetry={() => cacheQ.refetch()}
        retrying={cacheQ.isFetching}
      />
    );
  }
  if (cacheQ.isLoading || !cacheQ.data) {
    return (
      <div data-testid="tab-cache">
        <TabSkeleton rows={2} />
      </div>
    );
  }

  const c = cacheQ.data;

  return (
    <div data-testid="tab-cache" className="flex flex-col gap-6">
      <div className="flex items-baseline justify-between">
        <div>
          <p className="eyebrow">Embedding cache</p>
          <h2 className="mt-0.5 font-display text-base font-semibold tracking-tight">
            Re-uses embeddings to cut API cost
          </h2>
        </div>
        <button
          type="button"
          data-testid="btn-clear-cache"
          onClick={() => setClearOpen(true)}
          className="btn-danger btn-sm"
        >
          <Trash2 className="h-4 w-4" aria-hidden="true" /> Clear cache
        </button>
      </div>

      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <div className="panel grid place-items-center p-5">
          <HitRateGauge rate={c.hit_rate} />
        </div>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-2">
          <StatCard
            testId="stat-cache-entries"
            label="Cached entries"
            value={fmt(c.entry_count)}
            tone="accent"
            icon={<Database className="h-4 w-4" aria-hidden="true" />}
          />
          <StatCard
            testId="stat-cache-size"
            label="On-disk size"
            value={fmtBytes(c.size_bytes)}
            icon={<HardDrive className="h-4 w-4" aria-hidden="true" />}
          />
          <StatCard
            testId="stat-cache-hits"
            label="Hits"
            value={fmt(c.hits)}
            tone="run"
            icon={<Target className="h-4 w-4" aria-hidden="true" />}
          />
          <StatCard
            testId="stat-cache-misses"
            label="Misses"
            value={fmt(c.misses)}
            tone={c.misses > 0 ? "warn" : "idle"}
            icon={<XCircle className="h-4 w-4" aria-hidden="true" />}
          />
        </div>
      </div>

      <div className="panel p-5">
        <p className="eyebrow mb-3">Hit rate over time (%)</p>
        <RateChart data={trend} />
      </div>
      <CacheEconomicsPanel instanceId={id} />

      <ConfirmDialog
        open={clearOpen}
        title="Clear the embedding cache?"
        message="This drops all cached embeddings. The next index/query re-computes them, which may incur provider API cost. Indexed data is unaffected."
        confirmLabel="Clear cache"
        tone="danger"
        busy={clearM.isPending}
        onConfirm={() => clearM.mutate()}
        onCancel={() => setClearOpen(false)}
      />
    </div>
  );
}
