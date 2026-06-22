import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Network, RotateCcw } from "lucide-react";
import {
  getRuntimeConfigEffective,
  patchRuntimeConfig,
  getGlobalRuntimeConfigEffective,
  patchGlobalRuntimeConfig,
} from "../api/client";
import { SchemaForm } from "../components/SchemaForm/SchemaForm";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";
import { useOptionalSelectedInstance } from "../state/selectedInstance";
import type { ConfigValues, EffectiveConfig, UiSchema } from "../api/types";

// Runtime bind (config.json). Inherit-first; every field is `server`-type (read
// when the CLI starts the server). The instance layer resolves project > global
// > code default; the global layer resolves global > code default.
const RUNTIME_SCHEMA: UiSchema = {
  sections: [
    {
      key: "runtime",
      label: "Runtime bind (config.json) · server",
      description:
        "The bind the project server uses at start. Read by the CLI; the YAML server.*/api.* sections are a no-op for the running server. Changes apply on the next restart.",
      fields: [
        {
          key: "bind_host",
          dotpath: "bind_host",
          label: "Bind host",
          widget: "text",
          default: "127.0.0.1",
          help: "Interface to bind (e.g. 127.0.0.1, or 0.0.0.0 to expose).",
        },
        {
          key: "port_range_start",
          dotpath: "port_range_start",
          label: "Port range start",
          widget: "int",
          default: 8000,
          min: 1,
          max: 65535,
          help: "First port to try.",
        },
        {
          key: "port_range_end",
          dotpath: "port_range_end",
          label: "Port range end",
          widget: "int",
          default: 8100,
          min: 1,
          max: 65535,
          help: "Last port to try (≥ start).",
        },
        {
          key: "auto_port",
          dotpath: "auto_port",
          label: "Auto-port",
          widget: "toggle",
          default: true,
          help: "Scan the range for a free port at start. Off pins the start port.",
        },
      ],
    },
  ],
};

/**
 * Runtime bind editor — the per-project ``config.json`` bind. Rendered INSIDE
 * the Config tab (``scope="instance"``: project > global > code default) and on
 * the Global Config tab (``scope="global"``: machine-wide defaults, global > code
 * default). Same inline inherit-first control + Discard as the rest of Config.
 */
export function RuntimeSection({
  instanceId,
  scope = "instance",
}: {
  instanceId?: string;
  scope?: "instance" | "global";
}) {
  const ctx = useOptionalSelectedInstance();
  const id = instanceId ?? ctx?.selectedId ?? null;
  const isGlobal = scope === "global";
  const localSrc = isGlobal ? "global" : "file";
  const { toast } = useToast();
  const qc = useQueryClient();
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [pendingSave, setPendingSave] = useState<{
    values: ConfigValues;
    unset: string[];
    restart: boolean;
  } | null>(null);

  const effectiveQ = useQuery({
    queryKey: isGlobal
      ? ["global-runtime-config-effective"]
      : ["runtime-config-effective", id],
    queryFn: () =>
      isGlobal ? getGlobalRuntimeConfigEffective() : getRuntimeConfigEffective(id!),
    enabled: isGlobal || !!id,
  });

  const save = useMutation({
    mutationFn: ({
      values,
      unset,
      restart,
    }: {
      values: ConfigValues;
      unset: string[];
      restart: boolean;
    }) =>
      isGlobal
        ? patchGlobalRuntimeConfig(values, unset).then((r) => ({
            ...r,
            restarted: false,
          }))
        : patchRuntimeConfig(id!, values, restart, unset),
    onSuccess: (res) => {
      setFieldErrors({});
      if (isGlobal) {
        qc.invalidateQueries({ queryKey: ["global-runtime-config-effective"] });
        // Instance runtime effective inherits these defaults — refresh it too.
        qc.invalidateQueries({ queryKey: ["runtime-config-effective"] });
        toast(
          "Global runtime bind saved. Applies to project servers on their next start.",
          "success",
        );
        return;
      }
      qc.invalidateQueries({ queryKey: ["runtime-config", id] });
      qc.invalidateQueries({ queryKey: ["runtime-config-effective", id] });
      qc.invalidateQueries({ queryKey: ["instances"] });
      toast(
        (res as { restarted?: boolean }).restarted
          ? "Runtime bind saved — instance restarted."
          : "Runtime bind saved. Restart the instance to apply.",
        "success",
      );
    },
    onError: (err: unknown) => {
      if (err && typeof err === "object" && "errors" in err) {
        const map: Record<string, string> = {};
        for (const e of (err as { errors: { field: string; message: string }[] })
          .errors)
          map[e.field] = e.message;
        setFieldErrors(map);
        toast("Some runtime settings are invalid.", "error");
      } else {
        toast(err instanceof Error ? err.message : "Failed to save.", "error");
      }
    },
  });

  if (!isGlobal && !id) return null;

  if (effectiveQ.isError) {
    return (
      <div data-testid="runtime-section" role="alert" className="panel p-6 text-center">
        <p className="text-sm text-fg-muted">Could not load runtime config.</p>
        <p className="mt-1 font-mono text-xs text-fg-faint">
          {(effectiveQ.error as Error)?.message}
        </p>
        <button
          type="button"
          onClick={() => effectiveQ.refetch()}
          className="btn-ghost btn-sm mx-auto mt-4"
        >
          <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" /> Retry
        </button>
      </div>
    );
  }

  if (effectiveQ.isLoading || !effectiveQ.data) {
    return (
      <div data-testid="runtime-section" className="panel p-6">
        <div className="skeleton mb-3 h-9 w-full" />
        <div className="skeleton h-9 w-2/3" />
      </div>
    );
  }

  const eff = effectiveQ.data;
  const values: ConfigValues = {};
  for (const [key, entry] of Object.entries(eff)) {
    if (entry.source === localSrc) values[key] = entry.value;
  }
  const effective: EffectiveConfig = {};
  for (const [key, entry] of Object.entries(eff)) {
    effective[key] = {
      value: entry.value,
      source: entry.source,
      inherited: entry.inherited ?? null,
    };
  }

  return (
    <div data-testid={`runtime-section-${scope}`} className="flex flex-col gap-2">
      <div className="flex items-center gap-2.5">
        <span className="grid h-9 w-9 place-items-center rounded-xl bg-accent/15 text-accent">
          <Network className="h-5 w-5" aria-hidden="true" />
        </span>
        <div>
          <p className="eyebrow">{isGlobal ? "Control plane" : "Instance"}</p>
          <h2 className="font-display text-base font-semibold tracking-tight">
            {isGlobal ? "Global runtime bind" : "Runtime bind"}
          </h2>
          {isGlobal && (
            <p className="mt-0.5 text-xs text-fg-faint">
              Machine-wide bind defaults (<code>~/.config/brainpalace/config.json</code>)
              — every project inherits these unless its <code>config.json</code> overrides.
            </p>
          )}
        </div>
      </div>
      <SchemaForm
        schema={RUNTIME_SCHEMA}
        values={values}
        effective={effective}
        errors={fieldErrors}
        saving={save.isPending}
        localSource={localSrc}
        inheritFrom={isGlobal ? "default" : "global"}
        showRestart={!isGlobal}
        actionsInline
        idSuffix="-runtime"
        onSave={(v, unset, restart) =>
          setPendingSave({ values: v, unset, restart })
        }
      />
      <ConfirmDialog
        open={!!pendingSave}
        tone={pendingSave?.restart ? "danger" : "default"}
        title={
          isGlobal
            ? "Save global runtime bind?"
            : pendingSave?.restart
              ? "Save and restart instance?"
              : "Save runtime bind?"
        }
        message={
          isGlobal
            ? "Writes the machine-wide config.json. Project servers pick up the new defaults on their next start."
            : pendingSave?.restart
              ? "Writes config.json and restarts the server (brief downtime while it comes back up)."
              : "Writes config.json. The new bind applies on the next server start."
        }
        confirmLabel={pendingSave?.restart ? "Save + Restart" : "Save"}
        busy={save.isPending}
        onCancel={() => setPendingSave(null)}
        onConfirm={() => {
          if (pendingSave) save.mutate(pendingSave);
          setPendingSave(null);
        }}
      />
    </div>
  );
}
