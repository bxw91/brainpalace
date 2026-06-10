import { useMutation } from "@tanstack/react-query";
import { Loader2, PlugZap } from "lucide-react";
import { testProviders } from "../api/client";
import { useToast } from "./Toast";

/**
 * One-click live provider check. The embedding test makes a real (~1 token)
 * API call, so it only ever runs on explicit click — never on a poll.
 */
export function ProviderTest({ instanceId }: { instanceId: string }) {
  const { toast } = useToast();
  const testM = useMutation({
    mutationFn: () => testProviders(instanceId),
    onError: (e: unknown) =>
      toast(e instanceof Error ? e.message : "Provider test failed.", "error"),
  });
  const r = testM.data;

  return (
    <div data-testid="provider-test" className="panel flex flex-col gap-3 p-5">
      <div className="flex items-center justify-between">
        <p className="eyebrow">Provider connectivity</p>
        <button
          type="button"
          data-testid="btn-test-providers"
          disabled={testM.isPending}
          onClick={() => testM.mutate()}
          className="btn-primary btn-sm"
        >
          {testM.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <PlugZap className="h-4 w-4" aria-hidden="true" />
          )}
          Test now
        </button>
      </div>
      {r && (
        <ul className="flex flex-col gap-1.5 text-sm">
          {(
            [
              ["embedding", r.embedding, `${Math.round(r.embedding.latency_ms)} ms`],
              ["summarization", r.summarization, r.summarization.checked],
            ] as const
          ).map(([kind, res, detail]) => (
            <li key={kind} className="flex items-center gap-2">
              <span
                data-testid={`provider-chip-${kind}`}
                className={`rounded px-1.5 py-0.5 text-[0.65rem] ${
                  res.ok ? "bg-run/15 text-run" : "bg-bad/15 text-bad"
                }`}
              >
                {res.ok ? "ok" : "failed"}
              </span>
              <span className="font-mono text-xs text-fg">
                {kind}: {res.provider}/{res.model}
              </span>
              <span className="ml-auto text-xs text-fg-faint">{detail}</span>
              {res.error && (
                <span className="w-full truncate text-xs text-bad" title={res.error}>
                  {res.error}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
