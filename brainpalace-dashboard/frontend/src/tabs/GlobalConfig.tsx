import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Globe, RotateCcw } from "lucide-react";
import { getSchema, getGlobalConfig, patchGlobalConfig } from "../api/client";
import { SchemaForm } from "../components/SchemaForm/SchemaForm";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { DataConflictDialog } from "../components/DataConflictDialog";
import { useToast } from "../components/Toast";
import type {
  ConfigValues,
  ConfigErrorEnvelope,
  DataConflictEnvelope,
} from "../api/types";

function isErrorEnvelope(e: unknown): e is ConfigErrorEnvelope {
  return (
    !!e &&
    typeof e === "object" &&
    "errors" in e &&
    Array.isArray((e as ConfigErrorEnvelope).errors)
  );
}

function isConflict(e: unknown): e is DataConflictEnvelope {
  return (
    !!e &&
    typeof e === "object" &&
    (e as DataConflictEnvelope).conflict === "data_incompatible"
  );
}

/**
 * Global config editor — the machine-wide XDG `config.yaml` that every project
 * inherits (provider/graph/api defaults). Reuses the SchemaForm, but since this
 * IS the global layer there is no provenance/`effective` — the form renders the
 * file's own values + the schema directly. Changes apply to project servers on
 * their next start.
 */
export function GlobalConfig() {
  const { toast } = useToast();
  const qc = useQueryClient();
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [pendingSave, setPendingSave] = useState<ConfigValues | null>(null);
  const [conflict, setConflict] = useState<DataConflictEnvelope | null>(null);
  const [lastValues, setLastValues] = useState<ConfigValues | null>(null);

  const schemaQ = useQuery({
    queryKey: ["schema"],
    queryFn: getSchema,
    staleTime: 60_000,
  });
  const configQ = useQuery({
    queryKey: ["global-config"],
    queryFn: getGlobalConfig,
  });

  const mutation = useMutation({
    mutationFn: ({
      values,
      forceReindex,
    }: {
      values: ConfigValues;
      forceReindex?: boolean;
    }) => patchGlobalConfig(values, forceReindex ?? false),
    onSuccess: () => {
      setFieldErrors({});
      setConflict(null);
      toast("Global config saved. Applies to servers on their next start.", "success");
      qc.invalidateQueries({ queryKey: ["global-config"] });
    },
    onError: (err: unknown) => {
      if (isConflict(err)) {
        setConflict(err);
        return;
      }
      if (isErrorEnvelope(err)) {
        const map: Record<string, string> = {};
        for (const e of err.errors) {
          map[e.field] = e.suggestion ? `${e.message} — ${e.suggestion}` : e.message;
        }
        setFieldErrors(map);
        toast("Some settings could not be saved.", "error");
      } else {
        toast(
          err instanceof Error ? err.message : "Failed to save global config.",
          "error",
        );
      }
    },
  });

  if (schemaQ.isLoading || configQ.isLoading) {
    return (
      <div data-testid="tab-global-config" className="flex flex-col gap-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="panel p-6">
            <div className="skeleton mb-4 h-5 w-40" />
            <div className="skeleton mb-3 h-9 w-full" />
            <div className="skeleton h-9 w-2/3" />
          </div>
        ))}
      </div>
    );
  }

  if (schemaQ.isError || configQ.isError || !schemaQ.data || !configQ.data) {
    const reason = (configQ.error ?? schemaQ.error) as Error | undefined;
    const refetching = schemaQ.isFetching || configQ.isFetching;
    return (
      <div
        data-testid="tab-global-config"
        role="alert"
        className="panel grid place-items-center p-12"
      >
        <div className="text-center">
          <p className="text-sm text-fg-muted">Could not load global config.</p>
          {reason?.message && (
            <p className="mt-1 font-mono text-xs text-fg-faint">{reason.message}</p>
          )}
          <button
            type="button"
            data-testid="global-config-error-retry"
            disabled={refetching}
            onClick={() => {
              void schemaQ.refetch();
              void configQ.refetch();
            }}
            className="btn-ghost btn-sm mx-auto mt-4"
          >
            <RotateCcw
              className={`h-3.5 w-3.5 ${refetching ? "animate-spin" : ""}`}
              aria-hidden="true"
            />
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="tab-global-config" className="flex flex-col gap-4">
      <div className="flex items-center gap-2.5">
        <span className="grid h-9 w-9 place-items-center rounded-xl bg-accent/15 text-accent">
          <Globe className="h-5 w-5" aria-hidden="true" />
        </span>
        <div>
          <p className="eyebrow">Control plane</p>
          <h2 className="font-display text-base font-semibold tracking-tight">
            Global config
          </h2>
          <p className="mt-0.5 text-xs text-fg-faint">
            Machine-wide <code>~/.config/brainpalace/config.yaml</code> — every
            project inherits these unless it overrides them.
          </p>
        </div>
      </div>
      <SchemaForm
        schema={schemaQ.data}
        values={configQ.data}
        errors={fieldErrors}
        saving={mutation.isPending}
        showRestart={false}
        onSave={(values) => setPendingSave(values)}
      />
      <ConfirmDialog
        open={!!pendingSave}
        tone="default"
        title="Save global config?"
        message="Writes the machine-wide config.yaml. Project servers pick up the changes on their next start."
        confirmLabel="Save"
        busy={mutation.isPending}
        onCancel={() => setPendingSave(null)}
        onConfirm={() => {
          if (pendingSave) {
            setLastValues(pendingSave);
            mutation.mutate({ values: pendingSave });
          }
          setPendingSave(null);
        }}
      />
      <DataConflictDialog
        conflict={conflict}
        busy={mutation.isPending}
        onCancel={() => setConflict(null)}
        onReindex={() => {
          if (lastValues) {
            mutation.mutate({ values: lastValues, forceReindex: true });
          }
        }}
      />
    </div>
  );
}
