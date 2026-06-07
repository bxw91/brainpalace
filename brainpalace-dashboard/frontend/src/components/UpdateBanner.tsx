import { useQuery } from "@tanstack/react-query";
import { ArrowUpCircle } from "lucide-react";
import { getUpdateCheck } from "../api/client";

/**
 * Top-of-app banner that appears only when PyPI reports a newer brainpalace
 * release. Best-effort: the query is non-retrying and the banner stays hidden
 * on any error or when already up to date.
 */
export function UpdateBanner() {
  const { data } = useQuery({
    queryKey: ["update-check"],
    queryFn: getUpdateCheck,
    retry: false,
    staleTime: 6 * 3600 * 1000,
    refetchInterval: 6 * 3600 * 1000,
    refetchOnWindowFocus: false,
  });

  if (!data?.update_available || !data.latest) return null;

  return (
    <div
      data-testid="update-banner"
      role="status"
      className="flex items-center gap-2 border-b border-accent/30 bg-accent/10 px-6 py-2 text-sm text-accent"
    >
      <ArrowUpCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span>
        BrainPalace <span className="font-mono font-semibold">{data.latest}</span> is
        available (you have <span className="font-mono">{data.current}</span>). Run{" "}
        <code className="rounded bg-ink-900/40 px-1 py-0.5 font-mono text-xs">
          brainpalace update
        </code>{" "}
        to upgrade.
      </span>
    </div>
  );
}
