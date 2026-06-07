import { AlertCircle } from "lucide-react";
import type { SchemaField } from "../../api/types";
import { EnumField } from "./widgets/EnumField";
import { ToggleField } from "./widgets/ToggleField";
import { IntField } from "./widgets/IntField";
import { TextField } from "./widgets/TextField";
import { GroupField } from "./widgets/GroupField";

export type FieldProps = {
  field: SchemaField;
  getValue: (dotpath: string) => unknown;
  setValue: (dotpath: string, value: unknown) => void;
  errors?: Record<string, string>;
};

/** Human-readable rendering of a field's default value. */
function fmtDefault(v: unknown): string {
  if (v === null || v === undefined || v === "") return "none";
  if (typeof v === "boolean") return v ? "on" : "off";
  return String(v);
}

/** Renders one schema field (label + control + help + inline error). */
export function Field({ field, getValue, setValue, errors }: FieldProps) {
  if (field.widget === "group") {
    return (
      <GroupField
        field={field}
        getValue={getValue}
        setValue={setValue}
        errors={errors}
      />
    );
  }

  const raw = getValue(field.dotpath);
  const error = errors?.[field.dotpath];

  let control: React.ReactNode;
  switch (field.widget) {
    case "enum":
      control = (
        <EnumField
          dotpath={field.dotpath}
          options={field.options ?? []}
          value={raw === undefined ? undefined : String(raw)}
          defaultValue={
            field.default === undefined || field.default === null
              ? undefined
              : String(field.default)
          }
          onChange={(v) => setValue(field.dotpath, v)}
        />
      );
      break;
    case "toggle":
      control = (
        <ToggleField
          dotpath={field.dotpath}
          label={field.label}
          value={Boolean(raw)}
          onChange={(v) => setValue(field.dotpath, v)}
        />
      );
      break;
    case "int":
      control = (
        <IntField
          dotpath={field.dotpath}
          value={
            typeof raw === "number"
              ? raw
              : Number(raw) ||
                (typeof field.default === "number"
                  ? field.default
                  : (field.min ?? 0))
          }
          min={field.min}
          max={field.max}
          step={field.step}
          onChange={(v) => setValue(field.dotpath, v)}
        />
      );
      break;
    case "text":
    default:
      control = (
        <TextField
          dotpath={field.dotpath}
          value={raw === undefined || raw === null ? "" : String(raw)}
          secret={field.secret}
          placeholder={
            field.placeholder ??
            (field.default != null && field.default !== ""
              ? String(field.default)
              : undefined)
          }
          presets={field.presets}
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
          {field.default !== undefined && (
            <span
              data-testid={`field-default-${field.dotpath}`}
              className="ml-2 font-normal text-xs text-fg-faint"
            >
              default: {fmtDefault(field.default)}
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
