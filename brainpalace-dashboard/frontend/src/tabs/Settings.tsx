import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ServerCog, RotateCcw } from "lucide-react";
import { getSettings, patchSettings } from "../api/client";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";

type Draft = { host: string; port: number; poll_s: number; token: string };

/**
 * Control-plane ("server") settings — the dashboard's OWN config, separate from
 * the per-instance Config tab. Edits the `dashboard:` block of the XDG
 * config.yaml. host/port/token take effect on the next `brainpalace dashboard`
 * restart; poll_s applies on browser reload.
 */
export function Settings() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const settingsQ = useQuery({ queryKey: ["settings"], queryFn: getSettings });

  // Seed the editable draft once the settings load.
  useEffect(() => {
    if (settingsQ.data && !draft) {
      setDraft({
        host: settingsQ.data.host,
        port: settingsQ.data.port,
        poll_s: settingsQ.data.poll_s,
        token: settingsQ.data.token, // "********" when set, "" when unset
      });
    }
  }, [settingsQ.data, draft]);

  const save = useMutation({
    mutationFn: (d: Draft) =>
      patchSettings({
        host: d.host,
        port: d.port,
        poll_s: d.poll_s,
        token: d.token,
      }),
    onSuccess: (res) => {
      setErrors({});
      setConfirmOpen(false);
      qc.invalidateQueries({ queryKey: ["settings"] });
      const note =
        res.restart_required.length > 0
          ? ` Restart the dashboard to apply: ${res.restart_required.join(", ")}.`
          : "";
      toast(`Settings saved.${note}`, "success");
    },
    onError: (err: unknown) => {
      setConfirmOpen(false);
      if (err && typeof err === "object" && "errors" in err) {
        const map: Record<string, string> = {};
        for (const e of (err as { errors: { field: string; message: string }[] })
          .errors)
          map[e.field] = e.message;
        setErrors(map);
        toast("Some settings are invalid.", "error");
      } else {
        toast(err instanceof Error ? err.message : "Failed to save.", "error");
      }
    },
  });

  // Error must be checked BEFORE the `!draft` skeleton — on a failed load the
  // draft is never seeded, so a draft-gated skeleton would loop forever.
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

  if (settingsQ.isLoading || !draft) {
    return (
      <div data-testid="tab-settings" className="panel max-w-xl p-6">
        <div className="skeleton mb-3 h-9 w-full" />
        <div className="skeleton h-9 w-2/3" />
      </div>
    );
  }

  // Control-plane defaults (DashboardConfig). Shown so users see what's active
  // when a setting is unset.
  const DEFAULTS: Record<keyof Draft, string> = {
    host: "127.0.0.1",
    port: "8787",
    poll_s: "5",
    token: "none",
  };

  const field = (
    key: keyof Draft,
    label: string,
    hint: string,
    type: "text" | "number" | "password",
  ) => (
    <label className="flex flex-col gap-1" data-testid={`field-${key}`}>
      <span className="text-sm font-medium text-fg">
        {label}
        <span className="ml-2 font-normal text-xs text-fg-faint">
          default: {DEFAULTS[key]}
        </span>
      </span>
      <input
        data-testid={`input-${key}`}
        type={type}
        value={draft[key]}
        onChange={(e) =>
          setDraft({
            ...draft,
            [key]: type === "number" ? Number(e.target.value) : e.target.value,
          })
        }
        className="rounded-lg border border-line bg-ink-700/50 px-3 py-2 text-sm text-fg focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/30"
      />
      <span className="text-xs text-fg-faint">{hint}</span>
      {errors[key] && (
        <span
          data-testid={`field-error-${key}`}
          className="text-xs text-bad"
        >
          {errors[key]}
        </span>
      )}
    </label>
  );

  return (
    <div data-testid="tab-settings" className="flex max-w-xl flex-col gap-6">
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

      <div className="panel flex flex-col gap-5 p-6">
        {field("host", "Bind host", "Applies on dashboard restart.", "text")}
        {field("port", "Port", "Preferred port (scanned upward). Restart to apply.", "number")}
        {field("poll_s", "Poll interval (s)", "SPA fallback poll. Applies on reload.", "number")}
        {field(
          "token",
          "Bearer token",
          "Guards /dashboard/api/** when set. Leave blank to disable. Restart to apply.",
          "password",
        )}
      </div>

      <div className="flex justify-end">
        <button
          type="button"
          data-testid="btn-save-settings"
          onClick={() => setConfirmOpen(true)}
          disabled={save.isPending}
          className="btn-primary btn-sm"
        >
          Save settings
        </button>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        tone="default"
        title="Save dashboard settings?"
        message="Writes the dashboard: block of your XDG config.yaml. host/port/token take effect on the next dashboard restart; poll interval applies on reload."
        confirmLabel="Save"
        busy={save.isPending}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => draft && save.mutate(draft)}
      />
    </div>
  );
}
