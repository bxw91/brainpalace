import { AlertCircle } from "lucide-react";
import type {
  SchemaField,
  EffectiveConfig,
  EffectiveSource,
  ProvidersDescriptor,
} from "../../api/types";
import { IntField } from "./widgets/IntField";
import { TextField } from "./widgets/TextField";
import { GroupField } from "./widgets/GroupField";
import { DictField } from "./widgets/DictField";
import { StringListField } from "./widgets/StringListField";

export type FieldProps = {
  field: SchemaField;
  getValue: (dotpath: string) => unknown;
  setValue: (dotpath: string, value: unknown) => void;
  errors?: Record<string, string>;
  /** Per-key effective value + provenance (project > global > default). */
  effective?: EffectiveConfig;
  /** Canonical provider descriptor — drives conditional model/base_url/env. */
  providers?: ProvidersDescriptor;
  /** Revert a key to its inherited value (staged in the draft, saved on Save). */
  onInherit?: (dotpath: string) => void;
  /** Which provenance source counts as "set in THIS file" (the local layer).
   *  "project" for the instance tab, "global" for the global tab, "file" for
   *  single-scope surfaces (settings/runtime). */
  localSource?: "project" | "global" | "file";
  /** The immediate parent layer this surface inherits FROM. The inherit option
   *  is shown only when that exact layer holds a real value:
   *  - "global" (instance Config / instance Runtime): "using global value: X",
   *    hidden when no global override exists for the key;
   *  - "default" (Global / Settings / global Runtime): "using code default: X",
   *    hidden when the field has no code default. */
  inheritFrom?: "global" | "default";
};

/**
 * Provider-driven reshaping for the embedding/summarization/reranker sections.
 * Reads the section's currently-selected provider (form state → effective →
 * field default) and, for `model` / `base_url` / `api_key_env`, returns the
 * model presets, whether base_url applies, and the expected api_key_env. Fully
 * data-driven — no per-provider JSX branches. Returns null for non-provider
 * sections / fields so callers fall back to the static schema.
 */
function providerOverride(
  field: SchemaField,
  getValue: (dotpath: string) => unknown,
  effective: EffectiveConfig | undefined,
  providers: ProvidersDescriptor | undefined,
): { presets?: string[]; hidden?: boolean; placeholder?: string } | null {
  if (!providers) return null;
  const parts = field.dotpath.split(".");
  const section = parts[0];
  const leaf = parts[parts.length - 1];
  const kind = providers[section];
  // Only the model/base_url/api_key_env leaves of a provider section react.
  if (!kind || parts.length !== 2) return null;
  if (leaf !== "model" && leaf !== "base_url" && leaf !== "api_key_env") {
    return null;
  }
  const providerPath = `${section}.provider`;
  const raw = getValue(providerPath);
  const eff = effective?.[providerPath]?.value;
  const selected = (raw ?? eff) as string | undefined;
  const info = selected ? kind[selected] : undefined;
  if (!info) return null;
  if (leaf === "model") return { presets: info.models };
  if (leaf === "base_url") return { hidden: !info.needs_base_url };
  // api_key_env: surface the provider's conventional env var as placeholder.
  return { placeholder: info.default_api_key_env ?? undefined };
}

/** Human-readable rendering of a field's value. */
function fmtValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "none";
  if (typeof v === "boolean") return v ? "on" : "off";
  return String(v);
}

// No border/box around the group — each option carries its OWN border so every
// choice reads as a distinct selectable button, not just the active one.
const SEG_WRAP = "inline-flex flex-wrap items-center gap-2";

function segClass(active: boolean): string {
  return [
    "rounded-md border px-3 py-1.5 text-sm font-medium transition-all duration-150",
    "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
    active
      ? "border-accent bg-accent text-ink-900 shadow-sm"
      : "border-line bg-ink-900/40 text-fg-muted hover:border-accent/50 hover:bg-ink-700/60 hover:text-fg",
  ].join(" ");
}

export function Field({
  field,
  getValue,
  setValue,
  errors,
  effective,
  providers,
  onInherit,
  localSource = "project",
  inheritFrom = "default",
}: FieldProps) {
  if (field.widget === "group") {
    return (
      <GroupField
        field={field}
        getValue={getValue}
        setValue={setValue}
        errors={errors}
        effective={effective}
        onInherit={onInherit}
        localSource={localSource}
        inheritFrom={inheritFrom}
      />
    );
  }

  // Init-managed identity fields (state_dir / project_root): visible for
  // transparency but never editable — no inherit/override, no widget, no save.
  if (field.readonly) {
    const roRaw = getValue(field.dotpath);
    const roEff = effective?.[field.dotpath]?.value;
    const display =
      roRaw !== undefined && roRaw !== null && roRaw !== ""
        ? String(roRaw)
        : roEff !== undefined && roEff !== null && roEff !== ""
          ? String(roEff)
          : "—";
    return (
      <div
        data-testid={`field-${field.dotpath}`}
        data-field={field.dotpath}
        className="flex flex-col gap-1 py-1"
      >
        <label className="block text-sm font-medium text-fg">{field.label}</label>
        <div
          data-testid={`field-readonly-${field.dotpath}`}
          className="flex flex-wrap items-center gap-2"
        >
          <code className="rounded bg-ink-900/60 px-2 py-1 text-xs text-fg-muted">
            {display}
          </code>
          <span className="text-[11px] text-fg-faint">
            managed by init — read-only
          </span>
        </div>
        {field.help && (
          <p className="mt-0.5 max-w-prose text-xs leading-relaxed text-fg-faint">
            {field.help}
          </p>
        )}
      </div>
    );
  }

  // Provider-driven reshaping (model presets, base_url visibility, api_key_env
  // placeholder) keyed off the section's selected provider.
  const ov = providerOverride(field, getValue, effective, providers);
  if (ov?.hidden) return null;
  const presets = ov?.presets ?? field.presets;
  const placeholder = ov?.placeholder ?? field.placeholder;

  const dp = field.dotpath;
  const raw = getValue(dp);
  const error = errors?.[dp];
  // Inheriting = nothing staged in the draft for this key. A set value (incl.
  // null / "") is an override; only `undefined` means "inherit".
  const inheriting = raw === undefined;

  // What the key inherits TO (shown on the first option): the value it resolves
  // to with NO local override, AND where that value comes from.
  //
  // On the instance Config / Runtime surface (inheritFrom="global") the chain is
  // global → code default: show the global value when one is set, otherwise fall
  // back to the field's code default (still shown, labelled "using code default")
  // — never blank. On the Global / Settings surface (inheritFrom="default") the
  // only parent is the code default.
  const eff = effective?.[dp];
  let targetValue: unknown;
  let targetSource: EffectiveSource | undefined;
  if (inheritFrom === "default") {
    targetValue = field.default;
    targetSource = field.default != null ? "default" : undefined;
  } else if (eff == null) {
    // Key absent from the effective payload: fall back to the schema default.
    targetValue = field.default;
    targetSource = field.default != null ? "default" : undefined;
  } else if (eff.source === "project") {
    // Overridden locally → what it would revert to (global, else code default).
    targetValue = eff.inherited?.value ?? field.default;
    targetSource =
      eff.inherited?.source ?? (field.default != null ? "default" : undefined);
  } else {
    // Currently inheriting: eff already points at global or the code default.
    targetValue = eff.value;
    targetSource = eff.source;
  }
  const startVal =
    typeof targetValue === "number"
      ? targetValue
      : typeof field.default === "number"
        ? field.default
        : undefined;
  // Offer "inherit" whenever the resolved parent value is real. Only a field
  // with no parent value at all (e.g. an API-key env var with no code default)
  // shows just the input.
  const hasInheritValue =
    targetValue !== null && targetValue !== undefined && targetValue !== "";
  const showInherit = Boolean(onInherit) && hasInheritValue;
  const inheritLabel =
    targetSource === "global" ? "using global value" : "using code default";

  const inheritBtn = showInherit ? (
    <button
      type="button"
      role="radio"
      aria-checked={inheriting}
      data-testid={`field-inherit-${dp}`}
      onClick={() => onInherit?.(dp)}
      title="Inherit this value — staged until you Save"
      className={segClass(inheriting)}
    >
      <span className="opacity-70">{inheritLabel}:</span>{" "}
      {fmtValue(targetValue)}
    </button>
  ) : null;

  // The value control. enum/toggle render their choices inline in the SAME
  // segmented row as the inherit option (one radiogroup); text/int/dict/list
  // reuse their widget beside the inherit option (the input IS the override).
  let row: React.ReactNode;
  switch (field.widget) {
    case "enum": {
      const opts = field.options ?? [];
      row = (
        <div role="radiogroup" data-testid={`enum-${dp}`} className={SEG_WRAP}>
          {inheritBtn}
          {opts.map((opt) => {
            const active = !inheriting && String(raw) === opt;
            return (
              <button
                key={opt}
                type="button"
                role="radio"
                aria-checked={active}
                data-selected={active ? "true" : "false"}
                data-testid={`enum-${dp}-${opt}`}
                onClick={() => setValue(dp, opt)}
                className={segClass(active)}
              >
                {opt}
              </button>
            );
          })}
        </div>
      );
      break;
    }
    case "toggle": {
      const choices: Array<[string, boolean]> = [
        ["On", true],
        ["Off", false],
      ];
      row = (
        <div role="radiogroup" data-testid={`toggle-${dp}`} className={SEG_WRAP}>
          {inheritBtn}
          {choices.map(([lbl, b]) => {
            const active = !inheriting && Boolean(raw) === b;
            return (
              <button
                key={lbl}
                type="button"
                role="radio"
                aria-checked={active}
                data-testid={`toggle-${dp}-${lbl.toLowerCase()}`}
                onClick={() => setValue(dp, b)}
                className={segClass(active)}
              >
                {lbl}
              </button>
            );
          })}
        </div>
      );
      break;
    }
    case "int":
      row = (
        <div className="flex flex-wrap items-center gap-2">
          {inheritBtn}
          <IntField
            dotpath={dp}
            value={typeof raw === "number" ? raw : undefined}
            start={startVal}
            min={field.min}
            max={field.max}
            step={field.step}
            onChange={(v) => setValue(dp, v)}
          />
        </div>
      );
      break;
    case "dict":
      row = (
        <div className="flex flex-col gap-2">
          <div>{inheritBtn}</div>
          <DictField
            dotpath={dp}
            value={
              raw && typeof raw === "object" && !Array.isArray(raw)
                ? (raw as Record<string, unknown>)
                : undefined
            }
            onChange={(v) => setValue(dp, v)}
          />
        </div>
      );
      break;
    case "stringlist":
      row = (
        <div className="flex flex-col gap-2">
          <div>{inheritBtn}</div>
          <StringListField
            dotpath={dp}
            value={Array.isArray(raw) ? (raw as string[]) : undefined}
            onChange={(v) => setValue(dp, v)}
          />
        </div>
      );
      break;
    case "text":
    default:
      row = (
        <div className="flex flex-wrap items-center gap-2">
          {inheritBtn}
          <TextField
            dotpath={dp}
            value={raw === undefined || raw === null ? "" : String(raw)}
            secret={field.secret}
            hasValue={!inheriting && raw !== ""}
            placeholder={placeholder}
            presets={presets}
            onChange={(v) => setValue(dp, v)}
          />
        </div>
      );
  }

  return (
    <div
      data-testid={`field-${dp}`}
      data-field={dp}
      className="flex flex-col gap-2 py-1"
    >
      <div>
        <label
          htmlFor={`input-${dp}`}
          className="block text-sm font-medium text-fg"
        >
          {field.label}
        </label>
        {field.help && (
          <p className="mt-0.5 max-w-prose text-xs leading-relaxed text-fg-faint">
            {field.help}
          </p>
        )}
      </div>
      {row}
      {error && (
        <p
          role="alert"
          data-testid={`field-error-${dp}`}
          className="flex items-center gap-1.5 text-xs font-medium text-bad"
        >
          <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {error}
        </p>
      )}
    </div>
  );
}
