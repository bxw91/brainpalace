import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Play, Pause } from "lucide-react";
import { getLogs } from "../api/client";
import { useOptionalSelectedInstance } from "../state/selectedInstance";
import {
  NoInstance,
  StoppedState,
  ErrorState,
  TabSkeleton,
  isUnreachable,
} from "../components/TabState";

const LEVELS = ["all", "DEBUG", "INFO", "WARNING", "ERROR"] as const;
const LINE_COUNTS = [100, 200, 500, 1000] as const;

function lineTone(line: string): string {
  const u = line.toUpperCase();
  if (u.includes("ERROR") || u.includes("CRITICAL")) return "text-bad";
  if (u.includes("WARN")) return "text-warn";
  if (u.includes("DEBUG")) return "text-fg-faint";
  return "text-fg-muted";
}

export function Logs({ instanceId }: { instanceId?: string }) {
  const ctx = useOptionalSelectedInstance();
  const id = instanceId ?? ctx?.selectedId ?? null;

  const [level, setLevel] = useState<string>("all");
  const [lines, setLines] = useState<number>(200);
  const [autoTail, setAutoTail] = useState(false);
  const paneRef = useRef<HTMLDivElement>(null);

  const logsQ = useQuery({
    queryKey: ["logs", id, lines, level],
    queryFn: () => getLogs(id!, lines, level === "all" ? undefined : level),
    enabled: !!id,
    retry: false,
    refetchInterval: autoTail ? 3000 : false,
  });

  // Keep the pane scrolled to the newest line while auto-tailing.
  useEffect(() => {
    if (autoTail && paneRef.current) {
      paneRef.current.scrollTop = paneRef.current.scrollHeight;
    }
  }, [logsQ.data, autoTail]);

  if (!id) {
    return <NoInstance testId="tab-logs" message="Select an instance to tail its server log." />;
  }
  if (isUnreachable(logsQ.error)) {
    return <StoppedState testId="logs-stopped" />;
  }
  if (logsQ.isError) {
    return (
      <ErrorState
        testId="logs-error"
        message={(logsQ.error as Error)?.message}
        onRetry={() => logsQ.refetch()}
        retrying={logsQ.isFetching}
      />
    );
  }
  if (logsQ.isLoading) {
    return (
      <div data-testid="tab-logs">
        <TabSkeleton rows={1} />
      </div>
    );
  }

  if (logsQ.data?.unavailable) {
    return (
      <div data-testid="logs-unavailable" className="panel p-8 text-center">
        <p className="text-sm text-fg-muted">
          Log tailing isn’t available on this instance.
        </p>
        <p className="mt-1 text-xs text-fg-faint">
          The server predates the <code>/health/logs</code> endpoint, or it has
          not written a log file yet. Restart the instance with a current server
          to enable it.
        </p>
      </div>
    );
  }

  const logLines = logsQ.data?.lines ?? [];

  return (
    <div data-testid="tab-logs" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor="select-log-level" className="sr-only">
          Filter by level
        </label>
        <select
          id="select-log-level"
          data-testid="select-log-level"
          value={level}
          onChange={(e) => setLevel(e.target.value)}
          className="rounded-lg border border-line bg-ink-700/50 px-3 py-1.5 text-sm text-fg focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/30"
        >
          {LEVELS.map((l) => (
            <option key={l} value={l}>
              {l === "all" ? "all levels" : l}
            </option>
          ))}
        </select>

        <div className="flex items-center gap-1.5">
          {LINE_COUNTS.map((n) => (
            <button
              key={n}
              type="button"
              data-testid={`btn-lines-${n}`}
              onClick={() => setLines(n)}
              className={lines === n ? "btn-primary btn-sm" : "btn-ghost btn-sm"}
            >
              {n}
            </button>
          ))}
        </div>

        <button
          type="button"
          data-testid="btn-autotail"
          aria-pressed={autoTail}
          onClick={() => setAutoTail((v) => !v)}
          className={`btn-sm ml-auto ${autoTail ? "btn-primary" : "btn-ghost"}`}
        >
          {autoTail ? (
            <Pause className="h-4 w-4" aria-hidden="true" />
          ) : (
            <Play className="h-4 w-4" aria-hidden="true" />
          )}
          {autoTail ? "Tailing" : "Auto-tail"}
        </button>
      </div>

      <div
        ref={paneRef}
        data-testid="log-pane"
        className="panel max-h-[70vh] overflow-auto p-4 font-mono text-xs leading-relaxed"
      >
        {logLines.length === 0 ? (
          <p className="py-8 text-center text-fg-faint">No log lines.</p>
        ) : (
          logLines.map((line, i) => (
            <div
              key={i}
              className={`whitespace-pre-wrap break-words ${lineTone(line)}`}
            >
              {line || " "}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
