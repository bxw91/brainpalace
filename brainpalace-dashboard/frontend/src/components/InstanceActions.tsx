import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Square, RotateCw, ExternalLink, Lock, Unlock } from "lucide-react";
import {
  startInstance,
  stopInstance,
  restartInstance,
  getInstanceStatus,
  patchConfig,
} from "../api/client";
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

function obj(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" ? (v as Record<string, unknown>) : {};
}

/**
 * Lifecycle controls (Start / Stop / Restart) for a single selected instance —
 * rendered in the instance detail header so the user no longer has to detour
 * through Server → Instances to bounce the instance they're already looking at.
 * Mirrors the confirm copy + react-query cache key of the Instances tab.
 *
 * Also exposes the read-only kill switch (`server.read_only`) right beside Stop,
 * so the provider kill switch is one click from the status page rather than
 * buried in the Config tab. Toggling writes the sparse override and restarts the
 * instance (read-only is resolved at startup), mirroring `brainpalace read-only`.
 */
export function InstanceActions({ instance }: { instance: Instance }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [pending, setPending] = useState<Kind | null>(null);
  const [roPending, setRoPending] = useState(false);

  const stopped = isStopped(instance.status);

  // Current effective read-only state — drives the toggle's label + position.
  // Only polled while the instance is up (a stopped server has no status).
  const statusQ = useQuery({
    queryKey: ["status", instance.id],
    queryFn: () => getInstanceStatus(instance.id),
    enabled: !stopped,
    retry: false,
    refetchInterval: 8000,
  });
  const readOnly = obj(statusQ.data?.features).read_only === true;

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

  const readOnlyMutation = useMutation({
    // Set the sparse `server.read_only` override and restart so it takes effect.
    mutationFn: (next: boolean) =>
      patchConfig(instance.id, { server: { read_only: next } }, true),
    onSuccess: (_res, next) => {
      toast(
        next
          ? `Read-only ON — provider calls disabled. Restarted ${instance.name}.`
          : `Read-only OFF — providers re-enabled. Restarted ${instance.name}.`,
        "success",
      );
      qc.invalidateQueries({ queryKey: ["status", instance.id] });
      qc.invalidateQueries({ queryKey: ["config", instance.id] });
      qc.invalidateQueries({ queryKey: ["config-effective", instance.id] });
      qc.invalidateQueries({ queryKey: ["instances"] });
    },
    onError: (e: unknown) =>
      toast(e instanceof Error ? e.message : "Failed to toggle read-only.", "error"),
  });

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
            data-testid="btn-detail-readonly"
            onClick={() => setRoPending(true)}
            className={readOnly ? "btn-ghost btn-sm text-warn" : "btn-ghost btn-sm"}
            aria-pressed={readOnly}
            title={
              readOnly
                ? "Read-only is ON — click to re-enable providers"
                : "Enable read-only mode (disable provider calls)"
            }
          >
            {readOnly ? (
              <Lock className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <Unlock className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            Read-only
          </button>
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

      <ConfirmDialog
        open={roPending}
        title={readOnly ? "Disable read-only mode" : "Enable read-only mode"}
        message={
          readOnly
            ? "Re-enable provider calls (embedding, summarization, remote rerank) and resume indexing? The instance will restart to apply."
            : "Disable all provider calls (embedding, summarization, remote rerank)? Indexing jobs are skipped, self-heal will not delete, and vector/hybrid queries fall back to BM25. The instance will restart to apply."
        }
        confirmLabel={readOnly ? "Turn off" : "Turn on"}
        tone={readOnly ? "default" : "danger"}
        busy={readOnlyMutation.isPending}
        onCancel={() => setRoPending(false)}
        onConfirm={() => {
          readOnlyMutation.mutate(!readOnly);
          setRoPending(false);
        }}
      />
    </div>
  );
}
