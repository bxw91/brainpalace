import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Play, Square, RotateCw, ExternalLink } from "lucide-react";
import { startInstance, stopInstance, restartInstance } from "../api/client";
import type { Instance } from "../api/types";
import { ConfirmDialog } from "./ConfirmDialog";
import { useToast } from "./Toast";

type Kind = "start" | "stop" | "restart";

const COPY: Record<Kind, { title: string; msg: string; label: string; verb: string }> = {
  start: { title: "Start instance", msg: "Start this instance?", label: "Start", verb: "Started" },
  stop: {
    title: "Stop instance",
    msg: "Stop this instance? In-flight queries will be interrupted.",
    label: "Stop",
    verb: "Stopped",
  },
  restart: { title: "Restart instance", msg: "Restart this instance?", label: "Restart", verb: "Restarted" },
};

const isStopped = (s: Instance["status"]) => s === "stopped" || s === "stale";

/**
 * Lifecycle controls (Start / Stop / Restart) for a single selected instance —
 * rendered in the instance detail header so the user no longer has to detour
 * through Server → Instances to bounce the instance they're already looking at.
 * Mirrors the confirm copy + react-query cache key of the Instances tab.
 */
export function InstanceActions({ instance }: { instance: Instance }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [pending, setPending] = useState<Kind | null>(null);

  const lifecycle = useMutation({
    mutationFn: async (kind: Kind) => {
      const fn =
        kind === "start" ? startInstance : kind === "stop" ? stopInstance : restartInstance;
      await fn(instance.id);
      return kind;
    },
    onSuccess: (kind) => {
      toast(`${COPY[kind].verb} ${instance.name}.`, "success");
      qc.invalidateQueries({ queryKey: ["instances"] });
    },
    onError: (e: unknown) =>
      toast(e instanceof Error ? e.message : "Action failed.", "error"),
  });

  const stopped = isStopped(instance.status);

  return (
    <div data-testid="instance-actions" className="flex items-center gap-1.5">
      {stopped ? (
        <button
          type="button"
          data-testid="btn-detail-start"
          onClick={() => setPending("start")}
          className="btn-primary btn-sm"
          title="Start"
        >
          <Play className="h-3.5 w-3.5" aria-hidden="true" />
          Start
        </button>
      ) : (
        <>
          {instance.base_url && (
            <a
              href={instance.base_url}
              target="_blank"
              rel="noreferrer"
              data-testid="btn-detail-open"
              className="btn-ghost btn-sm"
              title="Open server"
              aria-label={`Open ${instance.name}`}
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
            </a>
          )}
          <button
            type="button"
            data-testid="btn-detail-restart"
            onClick={() => setPending("restart")}
            className="btn-ghost btn-sm"
            title="Restart"
            aria-label={`Restart ${instance.name}`}
          >
            <RotateCw className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
          <button
            type="button"
            data-testid="btn-detail-stop"
            onClick={() => setPending("stop")}
            className="btn-danger btn-sm"
            title="Stop"
          >
            <Square className="h-3.5 w-3.5" aria-hidden="true" />
            Stop
          </button>
        </>
      )}

      <ConfirmDialog
        open={!!pending}
        title={pending ? COPY[pending].title : ""}
        message={pending ? COPY[pending].msg : ""}
        confirmLabel={pending ? COPY[pending].label : "Confirm"}
        tone={pending === "stop" ? "danger" : "default"}
        busy={lifecycle.isPending}
        onCancel={() => setPending(null)}
        onConfirm={() => {
          if (pending) lifecycle.mutate(pending);
          setPending(null);
        }}
      />
    </div>
  );
}
