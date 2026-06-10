import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { getDecisions, getDecisionTimeline } from "../api/client";

/**
 * Decision browser + temporal supersession timeline. Click a Decision node
 * to see every edge touching it, with closed validity windows marked
 * "superseded" — the sqlite temporal graph rendered for humans.
 */
export function DecisionTimeline({ instanceId }: { instanceId: string }) {
  const [contains, setContains] = useState("");
  const [entity, setEntity] = useState<string | null>(null);

  const decisionsQ = useQuery({
    queryKey: ["decisions", instanceId, contains],
    queryFn: () => getDecisions(instanceId, contains.trim() || undefined),
    retry: false,
  });
  const timelineQ = useQuery({
    queryKey: ["timeline", instanceId, entity],
    queryFn: () => getDecisionTimeline(instanceId, entity!),
    enabled: !!entity,
    retry: false,
  });

  const decisions = decisionsQ.data?.decisions ?? [];

  return (
    <div data-testid="decision-timeline" className="panel flex flex-col gap-3 p-5">
      <div className="flex items-center justify-between gap-3">
        <p className="eyebrow">Decisions & supersession timeline</p>
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-faint"
            aria-hidden="true"
          />
          <label htmlFor="input-decision-search" className="sr-only">
            Search decisions
          </label>
          <input
            id="input-decision-search"
            data-testid="input-decision-search"
            type="text"
            value={contains}
            onChange={(e) => setContains(e.target.value)}
            placeholder="Search decisions…"
            className="w-56 rounded-lg border border-line bg-ink-700/50 py-1.5 pl-9 pr-3 text-sm text-fg placeholder:text-fg-faint focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/30"
          />
        </div>
      </div>

      {decisionsQ.isLoading ? (
        <p className="text-sm text-fg-faint">Loading decisions…</p>
      ) : decisionsQ.isError ? (
        <p className="text-sm text-fg-faint">Couldn&apos;t load decisions.</p>
      ) : decisions.length === 0 ? (
        contains.trim() ? (
          <p className="text-sm text-fg-faint">
            No decisions match &quot;{contains.trim()}&quot;.
          </p>
        ) : (
          <p className="text-sm text-fg-faint">
            No Decision nodes in the graph yet (decisions appear after session
            extraction runs on the sqlite graph backend).
          </p>
        )
      ) : (
        <ul className="flex flex-wrap gap-1.5">
          {decisions.map((d) => (
            <li key={d.id}>
              <button
                type="button"
                onClick={() => setEntity(d.name)}
                aria-pressed={entity === d.name}
                className={
                  entity === d.name ? "btn-primary btn-sm" : "btn-ghost btn-sm"
                }
              >
                {d.name}
              </button>
            </li>
          ))}
        </ul>
      )}

      {entity && (
        <div className="flex items-center gap-2">
          <p className="text-xs text-fg-faint">Timeline — {entity}</p>
          <button
            type="button"
            aria-label="Clear selection"
            onClick={() => setEntity(null)}
            className="btn-ghost btn-sm"
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      )}

      {entity && timelineQ.data && (
        <div data-testid="timeline-rows" className="flex flex-col gap-1.5">
          {timelineQ.data.timeline.length === 0 && (
            <p className="text-sm text-fg-faint">No edges for this entity.</p>
          )}
          {timelineQ.data.timeline.map((row, i) => (
            <div
              key={i}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-line/60 bg-ink-700/30 px-3 py-2 text-sm"
            >
              <span className="font-mono text-xs text-fg-faint">
                {row.valid_from?.slice(0, 10) ?? "?"}
              </span>
              <span className="text-fg">{row.subject}</span>
              <span className="rounded bg-ink-600 px-1.5 py-0.5 font-mono text-[0.65rem] text-fg-muted">
                {row.predicate}
              </span>
              <span className="text-fg">{row.object}</span>
              {row.valid ? (
                <span className="ml-auto rounded bg-run/15 px-1.5 py-0.5 text-[0.65rem] text-run">
                  active
                </span>
              ) : (
                <span
                  data-testid="badge-superseded"
                  className="ml-auto rounded bg-warn/15 px-1.5 py-0.5 text-[0.65rem] text-warn"
                  title={`closed ${row.valid_until ?? ""}`}
                >
                  superseded
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
