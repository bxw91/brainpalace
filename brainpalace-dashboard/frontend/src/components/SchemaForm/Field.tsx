import { AlertCircle } from "lucide-react";
import type {
  SchemaField,
  EffectiveConfig,
  ProvidersDescriptor,
} from "../../api/types";
import { EnumField } from "./widgets/EnumField";
import { ToggleField } from "./widgets/ToggleField";
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

/** Human-readable rendering of a field's default value. */
function fmtDefault(v: unknown): string {
  if (v === null || v === undefined || v === "") return "none";
  if (typeof v === "boolean") return v ? "on" : "off";
  return String(v);
}

/** Renders one schema field (label + control + help + inline error). */
export function Field({
  field,
  getValue,
  setValue,
  errors,
  effective,
  providers,
}: FieldProps) {
  if (field.widget === "group") {
    return (
      <GroupField
        field={field}
        getValue={getValue}
        setValue={setValue}
        errors={errors}
        effective={effective}
      />
    );
  }

  // Provider-driven reshaping (model presets, base_url visibility, api_key_env
  // placeholder) keyed off the section's selected provider.
  const ov = providerOverride(field, getValue, effective, providers);
  if (ov?.hidden) return null;
  const presets = ov?.presets ?? field.presets;
  const placeholder = ov?.placeholder ?? field.placeholder;

  const raw = getValue(field.dotpath);
  const error = errors?.[field.dotpath];
  // A secret shows masking dots ONLY when a value is actually set (the read
  // payload returns the MASK string when set, empty otherwise). #3 empty-secret.
  const hasValue =
    raw !== undefined && raw !== null && !(typeof raw === "string" && raw === "");

  // A field is "set locally" when the project config.yaml carries a value
  // (empty string/array/object counts as unset). Otherwise it is inherited.
  const isEmptyCollection =
    (field.widget === "stringlist" && Array.isArray(raw) && raw.length === 0) ||
    (field.widget === "dict" &&
      raw !== null &&
      typeof raw === "object" &&
      Object.keys(raw as object).length === 0);
  const setLocally =
    raw !== undefined &&
    raw !== null &&
    !(field.widget === "text" && raw === "") &&
    !isEmptyCollection;
  const eff = effective?.[field.dotpath];
  const effValue = eff ? eff.value : field.default;

  // Provenance hint shown ONLY when the field is not set locally — so a value
  // set in this project shows no "default:" noise.
  let hint: string | null = null;
  if (!setLocally) {
    if (eff && eff.source === "global") {
      hint = `inherited from global: ${fmtDefault(eff.value)}`;
    } else if (effValue !== undefined) {
      hint = `default: ${fmtDefault(effValue)}`;
    }
  }

  let control: React.ReactNode;
  switch (field.widget) {
    case "enum":
      control = (
        <EnumField
          dotpath={field.dotpath}
          options={field.options ?? []}
          value={raw === undefined ? undefined : String(raw)}
          defaultValue={
            effValue === undefined || effValue === null
              ? undefined
              : String(effValue)
          }
          onChange={(v) => setValue(field.dotpath, v)}
        />
      );
      break;
    case "toggle":
      // Unset booleans reflect the effective (global/default) value so an
      // inherited "on" doesn't masquerade as a local "off"; the hint marks it.
      control = (
        <ToggleField
          dotpath={field.dotpath}
          label={field.label}
          value={Boolean(setLocally ? raw : effValue)}
          onChange={(v) => setValue(field.dotpath, v)}
        />
      );
      break;
    case "int":
      // Empty when unset (no default baked into the input); +/- start from the
      // effective default.
      control = (
        <IntField
          dotpath={field.dotpath}
          value={typeof raw === "number" ? raw : undefined}
          start={typeof effValue === "number" ? effValue : undefined}
          min={field.min}
          max={field.max}
          step={field.step}
          onChange={(v) => setValue(field.dotpath, v)}
        />
      );
      break;
    case "dict":
      control = (
        <DictField
          dotpath={field.dotpath}
          value={
            raw && typeof raw === "object" && !Array.isArray(raw)
              ? (raw as Record<string, unknown>)
              : undefined
          }
          onChange={(v) => setValue(field.dotpath, v)}
        />
      );
      break;
    case "stringlist":
      control = (
        <StringListField
          dotpath={field.dotpath}
          value={Array.isArray(raw) ? (raw as string[]) : undefined}
          onChange={(v) => setValue(field.dotpath, v)}
        />
      );
      break;
    case "text":
    default:
      // Default is shown beside the label (the hint), NOT inside the input.
      control = (
        <TextField
          dotpath={field.dotpath}
          value={raw === undefined || raw === null ? "" : String(raw)}
          secret={field.secret}
          hasValue={hasValue}
          placeholder={placeholder}
          presets={presets}
          onChange={(v) => setValue(field.dotpath, v)}
        />
      );
  }

  // Toggles read better with the control inline next to the label.
  const inline = field.widget === "toggle";

  return (
    <div
      data-testid={`field-${field.dotpath}`}
      data-field={field.dotpath}
      className={
        inline
          ? "flex items-center justify-between gap-4 py-1"
          : "flex flex-col gap-2 py-1"
      }
    >
      <div className={inline ? "" : ""}>
        <label
          htmlFor={`input-${field.dotpath}`}
          className="block text-sm font-medium text-fg"
        >
          {field.label}
          {hint && (
            <span
              data-testid={`field-default-${field.dotpath}`}
              className="ml-2 font-normal text-xs text-fg-faint"
            >
              {hint}
            </span>
          )}
        </label>
        {field.help && (
          <p className="mt-0.5 max-w-prose text-xs leading-relaxed text-fg-faint">
            {field.help}
          </p>
        )}
      </div>
      {control}
      {error && (
        <p
          role="alert"
          data-testid={`field-error-${field.dotpath}`}
          className="flex items-center gap-1.5 text-xs font-medium text-bad"
        >
          <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {error}
        </p>
      )}
    </div>
  );
}
