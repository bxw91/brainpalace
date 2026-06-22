import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ServerCog, RotateCcw } from "lucide-react";
import {
  getSettings,
  getSettingsEffective,
  patchSettings,
} from "../api/client";
import { SchemaForm } from "../components/SchemaForm/SchemaForm";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";
import type { ConfigValues, EffectiveConfig, UiSchema } from "../api/types";

/**
 * Control-plane ("server") settings — the dashboard's OWN config, separate from
 * the per-instance Config tab. Edits the `dashboard:` block of the XDG
 * config.yaml. Reuses the SchemaForm so it gets the same inline inherit-first
 * control + Discard + staged save: the provenance layer is file > code default,
 * so each field shows `using code default: X`. host/port/token take effect on
 * the next `brainpalace dashboard` restart; poll_s applies on browser reload.
 */

// Single-scope schema for the 7 dashboard settings (dotpath == flat key).
const SETTINGS_SCHEMA: UiSchema = {
  sections: [
    {
      key: "dashboard",
      label: "Dashboard settings",
      fields: [
        {
          key: "host",
          dotpath: "host",
          label: "Bind host",
          widget: "text",
          default: "127.0.0.1",
          help: "Interface the dashboard binds. Applies on dashboard restart.",
        },
        {
          key: "port",
          dotpath: "port",
          label: "Port",
          widget: "int",
          default: 8787,
          min: 1,
          max: 65535,
          help: "Preferred port (scanned upward). Restart to apply.",
        },
        {
          key: "poll_s",
          dotpath: "poll_s",
          label: "Poll interval (s)",
          widget: "int",
          default: 5,
          min: 1,
          help: "SPA fallback poll. Applies on reload.",
        },
        {
          key: "token",
          dotpath: "token",
          label: "Bearer token",
          widget: "text",
          secret: true,
          default: null, // no code default → inherit option hidden, input only
          help: "Guards /dashboard/api/** when set. Clear to disable. Restart to apply.",
        },
        {
          key: "autostart",
          dotpath: "autostart",
          label: "Auto-start on brainpalace start",
          widget: "toggle",
          default: true,
          help: "Bring up the dashboard whenever a project server starts. Applies on the next start.",
        },
        {
          key: "time_format",
          dotpath: "time_format",
          label: "Clock format",
          widget: "enum",
          options: ["24h", "12h"],
          default: "24h",
          help: "How times are shown across the dashboard. Applies on reload.",
        },
        {
          key: "date_format",
          dotpath: "date_format",
          label: "Date format",
          widget: "enum",
          options: ["dd.mm.yyyy", "mm.dd.yyyy", "yyyy-mm-dd"],
          default: "dd.mm.yyyy",
          help: "How display dates are formatted across the dashboard. Applies on reload.",
        },
      ],
    },
  ],
};

export function Settings() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [pendingSave, setPendingSave] = useState<{
    values: ConfigValues;
    unset: string[];
  } | null>(null);

  const settingsQ = useQuery({ queryKey: ["settings"], queryFn: getSettings });
  const effectiveQ = useQuery({
    queryKey: ["settings-effective"],
    queryFn: getSettingsEffective,
  });

  const save = useMutation({
    mutationFn: ({ values, unset }: { values: ConfigValues; unset: string[] }) =>
      patchSettings(values, unset),
    onSuccess: (res) => {
      setFieldErrors({});
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["settings-effective"] });
      const note =
        res.restart_required.length > 0
          ? ` Restart the dashboard to apply: ${res.restart_required.join(", ")}.`
          : "";
      toast(`Settings saved.${note}`, "success");
    },
    onError: (err: unknown) => {
      if (err && typeof err === "object" && "errors" in err) {
        const map: Record<string, string> = {};
        for (const e of (err as { errors: { field: string; message: string }[] })
          .errors)
          map[e.field] = e.message;
        setFieldErrors(map);
        toast("Some settings are invalid.", "error");
      } else {
        toast(err instanceof Error ? err.message : "Failed to save.", "error");
      }
    },
  });

  if (settingsQ.isError) {
    return (
      <div data-testid="tab-settings" role="alert" className="panel p-8 text-center">
        <p className="text-sm text-fg-muted">Could not load dashboard settings.</p>
        <p className="mt-1 text-xs text-fg-faint">
          {(settingsQ.error as Error)?.message ||
            "If you just upgraded, restart the dashboard: brainpalace dashboard stop && brainpalace dashboard start."}
        </p>
        <button
          type="button"
          onClick={() => settingsQ.refetch()}
          className="btn-ghost btn-sm mx-auto mt-4"
        >
          <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" /> Retry
        </button>
      </div>
    );
  }

  if (settingsQ.isLoading || effectiveQ.isLoading || !effectiveQ.data) {
    return (
      <div data-testid="tab-settings" className="panel max-w-xl p-6">
        <div className="skeleton mb-3 h-9 w-full" />
        <div className="skeleton h-9 w-2/3" />
      </div>
    );
  }

  // Sparse values = only fields actually set in dashboard.yaml (source "file");
  // fields at their code default are OMITTED so the form renders them inheriting.
  const eff = effectiveQ.data;
  const values: ConfigValues = {};
  for (const [key, entry] of Object.entries(eff)) {
    if (entry.source === "file") values[key] = entry.value;
  }
  // Reshape to the EffectiveConfig the form expects (value/source/inherited).
  const effective: EffectiveConfig = {};
  for (const [key, entry] of Object.entries(eff)) {
    effective[key] = { value: entry.value, source: entry.source, inherited: null };
  }

  return (
    <div data-testid="tab-settings" className="flex flex-col gap-4">
      <div className="flex items-center gap-2.5">
        <span className="grid h-9 w-9 place-items-center rounded-xl bg-accent/15 text-accent">
          <ServerCog className="h-5 w-5" aria-hidden="true" />
        </span>
        <div>
          <p className="eyebrow">Control plane</p>
          <h2 className="font-display text-base font-semibold tracking-tight">
            Dashboard settings
          </h2>
        </div>
        <span className="ml-auto font-mono text-xs text-fg-faint">
          v{settingsQ.data?.version}
          {settingsQ.data?.runtime?.base_url
            ? ` · ${settingsQ.data.runtime.base_url}`
            : ""}
        </span>
      </div>

      <SchemaForm
        schema={SETTINGS_SCHEMA}
        values={values}
        effective={effective}
        errors={fieldErrors}
        saving={save.isPending}
        showRestart={false}
        localSource="file"
        onSave={(v, unset) => setPendingSave({ values: v, unset })}
      />

      <ConfirmDialog
        open={!!pendingSave}
        tone="default"
        title="Save dashboard settings?"
        message="Writes the dashboard: block of your XDG config.yaml. host/port/token take effect on the next dashboard restart; poll interval applies on reload."
        confirmLabel="Save"
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
