import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Network, ServerOff, RotateCcw } from "lucide-react";
import { getRuntimeConfig, patchRuntimeConfig, type RuntimeConfig } from "../api/client";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { ToggleField } from "../components/SchemaForm/widgets/ToggleField";
import { useToast } from "../components/Toast";
import { useOptionalSelectedInstance } from "../state/selectedInstance";

type ErrEnvelope = { errors: { field: string; message: string }[] };
function isErrEnvelope(e: unknown): e is ErrEnvelope {
  return !!e && typeof e === "object" && "errors" in e && Array.isArray((e as ErrEnvelope).errors);
}

/**
 * Per-instance Runtime panel — edits the project's `config.json` bind
 * (bind_host / port range / auto_port). This is the source the CLI reads at
 * server start; the YAML `server.*`/`api.*` sections are a no-op for the running
 * server, so the bind is edited here. Changes need a RESTART to take effect.
 */
export function Runtime({ instanceId }: { instanceId?: string }) {
  const ctx = useOptionalSelectedInstance();
  const id = instanceId ?? ctx?.selectedId ?? null;
  const { toast } = useToast();
  const qc = useQueryClient();
  const [draft, setDraft] = useState<RuntimeConfig | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<{ restart: boolean } | null>(null);

  const cfgQ = useQuery({
    queryKey: ["runtime-config", id],
    queryFn: () => getRuntimeConfig(id!),
    enabled: !!id,
  });

  useEffect(() => {
    if (cfgQ.data && !draft) setDraft(cfgQ.data);
  }, [cfgQ.data, draft]);

  const save = useMutation({
    mutationFn: ({ values, restart }: { values: RuntimeConfig; restart: boolean }) =>
      patchRuntimeConfig(id!, values, restart),
    onSuccess: (res) => {
      setErrors({});
      qc.invalidateQueries({ queryKey: ["runtime-config", id] });
      qc.invalidateQueries({ queryKey: ["instances"] });
      toast(
        res.restarted
          ? "Runtime config saved — instance restarted."
          : "Runtime config saved. Restart the instance to apply.",
        "success",
      );
    },
    onError: (err: unknown) => {
      if (isErrEnvelope(err)) {
        const map: Record<string, string> = {};
        for (const e of err.errors) map[e.field] = e.message;
        setErrors(map);
        toast("Some runtime settings are invalid.", "error");
      } else {
        toast(err instanceof Error ? err.message : "Failed to save.", "error");
      }
    },
  });

  if (!id) {
    return (
      <div data-testid="tab-runtime" className="panel grid place-items-center p-12">
        <div className="text-center">
          <ServerOff className="mx-auto mb-3 h-6 w-6 text-fg-faint" aria-hidden="true" />
          <p className="text-sm text-fg-muted">Select an instance to edit its runtime bind.</p>
        </div>
      </div>
    );
  }

  if (cfgQ.isError) {
    return (
      <div data-testid="tab-runtime" role="alert" className="panel p-8 text-center">
        <p className="text-sm text-fg-muted">Could not load runtime config.</p>
        <p className="mt-1 font-mono text-xs text-fg-faint">
          {(cfgQ.error as Error)?.message}
        </p>
        <button
          type="button"
          onClick={() => cfgQ.refetch()}
          className="btn-ghost btn-sm mx-auto mt-4"
        >
          <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" /> Retry
        </button>
      </div>
    );
  }

  if (cfgQ.isLoading || !draft) {
    return (
      <div data-testid="tab-runtime" className="panel max-w-xl p-6">
        <div className="skeleton mb-3 h-9 w-full" />
        <div className="skeleton h-9 w-2/3" />
      </div>
    );
  }

  const numField = (
    key: "port_range_start" | "port_range_end",
    label: string,
    hint: string,
  ) => (
    <label className="flex flex-col gap-1" data-testid={`field-${key}`}>
      <span className="text-sm font-medium text-fg">{label}</span>
      <input
        data-testid={`input-${key}`}
        type="number"
        value={draft[key]}
        onChange={(e) => setDraft({ ...draft, [key]: Number(e.target.value) })}
        className="rounded-lg border border-line bg-ink-700/50 px-3 py-2 text-sm text-fg focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/30"
      />
      <span className="text-xs text-fg-faint">{hint}</span>
      {errors[key] && (
        <span data-testid={`field-error-${key}`} className="text-xs text-bad">
          {errors[key]}
        </span>
      )}
    </label>
  );

  return (
    <div data-testid="tab-runtime" className="flex max-w-xl flex-col gap-6">
      <div className="flex items-center gap-2.5">
        <span className="grid h-9 w-9 place-items-center rounded-xl bg-accent/15 text-accent">
          <Network className="h-5 w-5" aria-hidden="true" />
        </span>
        <div>
          <p className="eyebrow">Instance</p>
          <h2 className="font-display text-base font-semibold tracking-tight">
            Runtime bind
          </h2>
          <p className="mt-0.5 text-xs text-fg-faint">
            The <code>config.json</code> bind the server uses at start. Changes
            apply on the next restart.
          </p>
        </div>
      </div>

      <div className="panel flex flex-col gap-5 p-6">
        <label className="flex flex-col gap-1" data-testid="field-bind_host">
          <span className="text-sm font-medium text-fg">Bind host</span>
          <input
            data-testid="input-bind_host"
            type="text"
            value={draft.bind_host}
            onChange={(e) => setDraft({ ...draft, bind_host: e.target.value })}
            className="rounded-lg border border-line bg-ink-700/50 px-3 py-2 text-sm text-fg focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/30"
          />
          <span className="text-xs text-fg-faint">
            Interface to bind (e.g. 127.0.0.1, or 0.0.0.0 to expose).
          </span>
          {errors.bind_host && (
            <span data-testid="field-error-bind_host" className="text-xs text-bad">
              {errors.bind_host}
            </span>
          )}
        </label>
        {numField("port_range_start", "Port range start", "First port to try.")}
        {numField("port_range_end", "Port range end", "Last port to try (≥ start).")}
        <div className="flex items-start justify-between gap-4" data-testid="field-auto_port">
          <span className="flex flex-col gap-1">
            <span className="text-sm font-medium text-fg">Auto-port</span>
            <span className="text-xs text-fg-faint">
              Scan the range for a free port at start. Off pins the start port.
            </span>
          </span>
          <ToggleField
            dotpath="auto_port"
            value={draft.auto_port}
            onChange={(v) => setDraft({ ...draft, auto_port: v })}
            label="Auto-port"
          />
        </div>
      </div>

      <div className="flex justify-end gap-2">
        <button
          type="button"
          data-testid="btn-save-runtime-restart"
          onClick={() => setPending({ restart: true })}
          disabled={save.isPending}
          className="btn-ghost btn-sm"
        >
          Save + Restart
        </button>
        <button
          type="button"
          data-testid="btn-save-runtime"
          onClick={() => setPending({ restart: false })}
          disabled={save.isPending}
          className="btn-primary btn-sm"
        >
          Save
        </button>
      </div>

      <ConfirmDialog
        open={!!pending}
        tone={pending?.restart ? "danger" : "default"}
        title={pending?.restart ? "Save and restart instance?" : "Save runtime config?"}
        message={
          pending?.restart
            ? "Writes config.json and restarts the server (brief downtime while it comes back up)."
            : "Writes config.json. The new bind applies on the next server start."
        }
        confirmLabel={pending?.restart ? "Save + Restart" : "Save"}
        busy={save.isPending}
        onCancel={() => setPending(null)}
        onConfirm={() => {
          if (pending) save.mutate({ values: draft, restart: pending.restart });
          setPending(null);
        }}
      />
    </div>
  );
}
