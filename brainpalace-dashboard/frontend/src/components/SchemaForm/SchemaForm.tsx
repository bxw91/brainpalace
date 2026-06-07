import { useMemo } from "react";
import { RotateCcw, Save, RefreshCw } from "lucide-react";
import type {
  SchemaField,
  UiSchema,
  ConfigValues,
  EffectiveConfig,
} from "../../api/types";
import { Field } from "./Field";
import { useFormState } from "./useFormState";

/** Flatten a schema to the set of leaf (savable) dotpaths. */
function leafPaths(fields: SchemaField[]): string[] {
  const out: string[] = [];
  for (const f of fields) {
    if (f.widget === "group") out.push(...leafPaths(f.fields ?? []));
    else out.push(f.dotpath);
  }
  return out;
}

export function SchemaForm({
  schema,
  values,
  effective,
  onSave,
  errors,
  saving = false,
  showRestart = true,
}: {
  schema: UiSchema;
  values: ConfigValues;
  effective?: EffectiveConfig;
  onSave: (draft: ConfigValues, restart: boolean) => void;
  errors?: Record<string, string>;
  saving?: boolean;
  /** Hide the "Save + Restart" button (e.g. global config has no instance). */
  showRestart?: boolean;
}) {
  const allPaths = useMemo(
    () => schema.sections.flatMap((s) => leafPaths(s.fields)),
    [schema],
  );
  const form = useFormState(values, allPaths);

  return (
    <div data-testid="schema-form" className="flex flex-col gap-6 pb-28">
      {schema.sections.map((section) => (
        <section
          key={section.key}
          data-testid={`section-${section.key}`}
          className="panel p-6"
        >
          <h2 className="mb-4 font-display text-base font-semibold tracking-tight">
            {section.label}
          </h2>
          <div className="flex flex-col divide-y divide-line/60">
            {section.fields.map((field) => (
              <div key={field.dotpath} className="py-3 first:pt-0 last:pb-0">
                <Field
                  field={field}
                  getValue={form.getValue}
                  setValue={form.setValue}
                  errors={errors}
                  effective={effective}
                  providers={schema.providers}
                />
              </div>
            ))}
          </div>
        </section>
      ))}

      {/* Action bar is ALWAYS visible so Save / Save + Restart are discoverable;
          the buttons are disabled until there is something to save. */}
      <div
        data-testid="unsaved-banner"
        role="region"
        aria-label="Save configuration"
        className={[
          "panel animate-fade-up fixed bottom-6 left-1/2 z-40 flex -translate-x-1/2 items-center gap-4 px-5 py-3",
          form.dirty ? "border-accent/30 shadow-glow" : "border-line",
        ].join(" ")}
      >
        <span className="flex items-center gap-2 text-sm">
          {form.dirty ? (
            <>
              <span className="grid h-6 w-6 place-items-center rounded-full bg-accent/15 font-mono text-xs font-semibold text-accent">
                {form.changeCount}
              </span>
              <span className="text-fg-muted">
                {form.changeCount === 1
                  ? "1 unsaved change"
                  : `${form.changeCount} unsaved changes`}
              </span>
            </>
          ) : (
            <span className="text-fg-faint">No unsaved changes</span>
          )}
        </span>
        <div className="h-5 w-px bg-line" aria-hidden="true" />
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-testid="btn-discard"
            onClick={form.reset}
            disabled={saving || !form.dirty}
            className="btn-ghost btn-sm"
          >
            <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
            Discard
          </button>
          {showRestart && (
            <button
              type="button"
              data-testid="btn-save-restart"
              onClick={() => onSave(form.draft, true)}
              disabled={saving || !form.dirty}
              className="btn-ghost btn-sm"
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
              Save + Restart
            </button>
          )}
          <button
            type="button"
            data-testid="btn-save"
            onClick={() => onSave(form.draft, false)}
            disabled={saving || !form.dirty}
            className="btn-primary btn-sm"
          >
            <Save className="h-3.5 w-3.5" aria-hidden="true" />
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
