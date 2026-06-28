import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ServerOff, RotateCcw } from "lucide-react";
import {
  getSchema,
  getConfig,
  getConfigEffective,
  patchConfig,
} from "../api/client";
import { SchemaForm } from "../components/SchemaForm/SchemaForm";
import { ProviderTest } from "../components/ProviderTest";
import { ConfigDiff } from "../components/ConfigDiff";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { DataConflictDialog } from "../components/DataConflictDialog";
import { useToast } from "../components/Toast";
import { useOptionalSelectedInstance } from "../state/selectedInstance";
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

export function Config({ instanceId }: { instanceId?: string }) {
  const ctx = useOptionalSelectedInstance();
  const id = instanceId ?? ctx?.selectedId ?? null;
  const { toast } = useToast();
  const qc = useQueryClient();
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [pendingSave, setPendingSave] = useState<{
    values: ConfigValues;
    unset: string[];
    restart: boolean;
  } | null>(null);
  const [conflict, setConflict] = useState<DataConflictEnvelope | null>(null);
  const [lastSave, setLastSave] = useState<{
    values: ConfigValues;
    unset: string[];
  } | null>(null);

  const schemaQ = useQuery({
    queryKey: ["schema"],
    queryFn: getSchema,
    staleTime: 60_000,
  });
  const configQ = useQuery({
    queryKey: ["config", id],
    queryFn: () => getConfig(id!),
    enabled: !!id,
  });
  // Effective values (project > global > default) power the provenance hints.
  // Best-effort: if it fails, the form still renders from schema + project values.
  const effectiveQ = useQuery({
    queryKey: ["config-effective", id],
    queryFn: () => getConfigEffective(id!),
    enabled: !!id,
  });

  const mutation = useMutation({
    mutationFn: ({
      values,
      unset,
      restart,
      forceReindex,
    }: {
      values: ConfigValues;
      unset: string[];
      restart: boolean;
      forceReindex?: boolean;
    }) => patchConfig(id!, values, restart, forceReindex ?? false, unset),
    onSuccess: (res, vars) => {
      setFieldErrors({});
      setConflict(null);
      const reindexed = res.reindex_triggered;
      toast(
        reindexed != null
          ? `Config saved — reindexing ${reindexed} folder(s).`
          : vars.restart && res.restarted
            ? "Config saved — instance restarted."
            : "Config saved.",
        "success",
      );
      qc.invalidateQueries({ queryKey: ["config", id] });
      qc.invalidateQueries({ queryKey: ["config-effective", id] });
      qc.invalidateQueries({ queryKey: ["instances"] });
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
          err instanceof Error ? err.message : "Failed to save config.",
          "error",
        );
      }
    },
  });

  if (!id) {
    return (
      <div data-testid="tab-config" className="panel grid place-items-center p-12">
        <div className="text-center">
          <ServerOff className="mx-auto mb-3 h-6 w-6 text-fg-faint" aria-hidden="true" />
          <p className="text-sm text-fg-muted">
            Select an instance to edit its configuration.
          </p>
        </div>
      </div>
    );
  }

  if (schemaQ.isLoading || configQ.isLoading) {
    return (
      <div data-testid="tab-config" className="flex flex-col gap-4">
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

  const instanceOptions = (ctx?.instances ?? []).map((i) => ({
    id: i.id,
    name: i.name,
  }));

  if (schemaQ.isError || configQ.isError || !schemaQ.data || !configQ.data) {
    const reason = (configQ.error ?? schemaQ.error) as Error | undefined;
    const refetching = schemaQ.isFetching || configQ.isFetching;
    return (
      <div
        data-testid="tab-config"
        role="alert"
        className="panel grid place-items-center p-12"
      >
        <div className="text-center">
          <ServerOff className="mx-auto mb-3 h-6 w-6 text-bad" aria-hidden="true" />
          <p className="text-sm text-fg-muted">
            Could not load configuration.
          </p>
          {reason?.message && (
            <p className="mt-1 font-mono text-xs text-fg-faint">
              {reason.message}
            </p>
          )}
          <button
            type="button"
            data-testid="config-error-retry"
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
    <div data-testid="tab-config" className="flex flex-col gap-4">
      <SchemaForm
        schema={schemaQ.data}
        values={configQ.data}
        effective={effectiveQ.data}
        errors={fieldErrors}
        saving={mutation.isPending}
        inheritFrom="global"
        onSave={(values, unset, restart) =>
          setPendingSave({ values, unset, restart })
        }
      />
      {/* Provider connectivity check sits under all provider settings so it
          validates the values shown above. */}
      <ProviderTest instanceId={id} />
      <ConfirmDialog
        open={!!pendingSave}
        tone={pendingSave?.restart ? "danger" : "default"}
        title={pendingSave?.restart ? "Save and restart instance?" : "Save configuration?"}
        message={
          pendingSave?.restart
            ? "Writes the changes to config.yaml and restarts the server (brief downtime while it comes back up)."
            : "Writes the changes to config.yaml. They apply on the next server start."
        }
        confirmLabel={pendingSave?.restart ? "Save + Restart" : "Save"}
        busy={mutation.isPending}
        onCancel={() => setPendingSave(null)}
        onConfirm={() => {
          if (pendingSave) {
            setLastSave({ values: pendingSave.values, unset: pendingSave.unset });
            mutation.mutate(pendingSave);
          }
          setPendingSave(null);
        }}
      />
      <DataConflictDialog
        conflict={conflict}
        busy={mutation.isPending}
        onCancel={() => setConflict(null)}
        onReindex={() => {
          if (lastSave) {
            mutation.mutate({
              values: lastSave.values,
              unset: lastSave.unset,
              restart: false,
              forceReindex: true,
            });
          }
        }}
      />
      <ConfigDiff instanceId={id} instances={instanceOptions} />
    </div>
  );
}
