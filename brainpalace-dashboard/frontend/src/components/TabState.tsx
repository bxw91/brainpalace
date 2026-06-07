import type { ReactNode } from "react";
import { ServerOff, Power, AlertCircle, RotateCcw } from "lucide-react";
import { InstanceUnreachableError } from "../api/client";

/** Empty state shown by every per-instance tab when no instance is selected. */
export function NoInstance({ testId, message }: { testId: string; message: string }) {
  return (
    <div data-testid={testId} className="panel grid place-items-center p-12">
      <div className="text-center">
        <ServerOff className="mx-auto mb-3 h-6 w-6 text-fg-faint" aria-hidden="true" />
        <p className="text-sm text-fg-muted">{message}</p>
      </div>
    </div>
  );
}

/** Stopped-server state: the instance is down, prompt to Start it. */
export function StoppedState({ testId }: { testId: string }) {
  return (
    <div data-testid={testId} className="panel grid place-items-center p-12">
      <div className="text-center">
        <Power className="mx-auto mb-3 h-6 w-6 text-idle" aria-hidden="true" />
        <p className="text-sm text-fg-muted">
          This instance is stopped. Start it from the Instances tab to see live
          data.
        </p>
      </div>
    </div>
  );
}

/** Generic error banner for a failed data load, with an optional Retry. */
export function ErrorState({
  testId,
  message,
  onRetry,
  retrying = false,
}: {
  testId: string;
  message?: string;
  onRetry?: () => void;
  retrying?: boolean;
}) {
  return (
    <div
      data-testid={testId}
      role="alert"
      className="panel grid place-items-center p-12"
    >
      <div className="text-center">
        <AlertCircle className="mx-auto mb-3 h-6 w-6 text-bad" aria-hidden="true" />
        <p className="text-sm text-fg-muted">Could not load data.</p>
        {message && (
          <p className="mt-1 font-mono text-xs text-fg-faint">{message}</p>
        )}
        {onRetry && (
          <button
            type="button"
            data-testid={`${testId}-retry`}
            onClick={onRetry}
            disabled={retrying}
            className="btn-ghost btn-sm mx-auto mt-4"
          >
            <RotateCcw
              className={`h-3.5 w-3.5 ${retrying ? "animate-spin" : ""}`}
              aria-hidden="true"
            />
            Retry
          </button>
        )}
      </div>
    </div>
  );
}

export function isUnreachable(err: unknown): boolean {
  return err instanceof InstanceUnreachableError;
}

/** Stacked skeleton block used while a tab's data loads. */
export function TabSkeleton({ rows = 3 }: { rows?: number }): ReactNode {
  return (
    <div className="flex flex-col gap-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="panel p-6">
          <div className="skeleton mb-4 h-5 w-40" />
          <div className="skeleton mb-3 h-9 w-full" />
          <div className="skeleton h-9 w-2/3" />
        </div>
      ))}
    </div>
  );
}
