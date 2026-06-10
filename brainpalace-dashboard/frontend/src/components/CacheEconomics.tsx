import { useQuery } from "@tanstack/react-query";
import { getCacheEconomics } from "../api/client";
import { StatCard } from "./StatCard";

const usd = (v: number | null) =>
  v == null ? "—" : `$${v >= 0.01 ? v.toFixed(2) : v.toPrecision(2)}`;

/**
 * Estimated embedding spend + cache savings. Every figure is an estimate
 * (counters x avg tokens x published price) and is labeled as such; when the
 * provider has no known price (local models) no dollar figures are shown.
 */
export function CacheEconomicsPanel({ instanceId }: { instanceId: string }) {
  const econQ = useQuery({
    queryKey: ["cache-economics", instanceId],
    queryFn: () => getCacheEconomics(instanceId),
    retry: false,
    // Keep session counters fresh; matches the Cache tab's 60s polling.
    refetchInterval: 60_000,
  });
  const e = econQ.data;
  if (!e) return null;

  return (
    <div data-testid="cache-economics" className="panel flex flex-col gap-4 p-5">
      <div className="flex items-baseline justify-between">
        <p className="eyebrow">Cost estimate</p>
        <p className="text-[0.65rem] text-fg-faint">
          basis: {e.provider}/{e.model}
          {e.price_usd_per_mtok != null
            ? ` · $${e.price_usd_per_mtok}/Mtok · ~${e.avg_tokens_per_chunk} tok/chunk`
            : ""}
        </p>
      </div>
      {e.price_usd_per_mtok == null ? (
        <p data-testid="econ-no-price" className="text-sm text-fg-muted">
          No published price for {e.provider}/{e.model} (local or unknown model) —
          cache still saved {e.session_hits.toLocaleString()} embedding calls this
          session.
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-3">
          <StatCard
            testId="econ-saved"
            label="Saved by cache (session)"
            value={usd(e.est_saved_usd)}
            hint={`${e.session_hits.toLocaleString()} hits`}
            tone="run"
          />
          <StatCard
            testId="econ-spend"
            label="Embedding spend (session)"
            value={usd(e.est_spend_usd)}
            hint={`${e.session_misses.toLocaleString()} misses`}
          />
          <StatCard
            testId="econ-reindex"
            label="Full re-embed would cost"
            value={usd(e.est_reindex_cost_usd)}
            hint={`${e.cached_entries.toLocaleString()} cached entries`}
            tone="accent"
          />
        </div>
      )}
    </div>
  );
}
