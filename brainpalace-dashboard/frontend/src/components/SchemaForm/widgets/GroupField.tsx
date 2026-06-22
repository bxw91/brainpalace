import type { SchemaField, EffectiveConfig } from "../../../api/types";
import { Field } from "../Field";

/**
 * A nested fieldset (e.g. storage.postgres). Honors `visible_when` against the
 * current draft so dependent groups only show when their condition is met.
 */
export function GroupField({
  field,
  getValue,
  setValue,
  errors,
  effective,
  onInherit,
  localSource,
  inheritFrom,
}: {
  field: SchemaField;
  getValue: (dotpath: string) => unknown;
  setValue: (dotpath: string, value: unknown) => void;
  errors?: Record<string, string>;
  effective?: EffectiveConfig;
  onInherit?: (dotpath: string) => void;
  localSource?: "project" | "global" | "file";
  inheritFrom?: "global" | "default";
}) {
  if (field.visible_when) {
    const current = getValue(field.visible_when.field);
    if (String(current) !== field.visible_when.equals) return null;
  }

  return (
    <fieldset
      data-testid={`group-${field.dotpath}`}
      className="flex flex-col gap-4 rounded-xl border border-line bg-ink-900/30 p-4"
    >
      <legend className="px-1 font-mono text-[0.68rem] uppercase tracking-[0.18em] text-fg-faint">
        {field.label}
      </legend>
      {(field.fields ?? []).map((child) => (
        <Field
          key={child.dotpath}
          field={child}
          getValue={getValue}
          setValue={setValue}
          errors={errors}
          effective={effective}
          onInherit={onInherit}
          localSource={localSource}
          inheritFrom={inheritFrom}
        />
      ))}
    </fieldset>
  );
}
