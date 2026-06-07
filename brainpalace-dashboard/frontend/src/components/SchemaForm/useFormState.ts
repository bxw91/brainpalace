import { useCallback, useMemo, useState } from "react";
import type { ConfigValues } from "../../api/types";

export function getAt(obj: ConfigValues, dotpath: string): unknown {
  return dotpath.split(".").reduce<unknown>((acc, key) => {
    if (acc && typeof acc === "object" && key in (acc as object)) {
      return (acc as Record<string, unknown>)[key];
    }
    return undefined;
  }, obj);
}

/** Immutably set a value at a dotpath, cloning each touched level. */
export function setAt(
  obj: ConfigValues,
  dotpath: string,
  value: unknown,
): ConfigValues {
  const keys = dotpath.split(".");
  const root: ConfigValues = { ...obj };
  let cursor: Record<string, unknown> = root;
  for (let i = 0; i < keys.length - 1; i++) {
    const k = keys[i];
    const existing = cursor[k];
    const next =
      existing && typeof existing === "object" && !Array.isArray(existing)
        ? { ...(existing as Record<string, unknown>) }
        : {};
    cursor[k] = next;
    cursor = next;
  }
  cursor[keys[keys.length - 1]] = value;
  return root;
}

function stableStringify(v: unknown): string {
  return JSON.stringify(v, (_k, val) => {
    if (val && typeof val === "object" && !Array.isArray(val)) {
      return Object.keys(val as Record<string, unknown>)
        .sort()
        .reduce<Record<string, unknown>>((acc, key) => {
          acc[key] = (val as Record<string, unknown>)[key];
          return acc;
        }, {});
    }
    return val;
  });
}

export type FormState = {
  draft: ConfigValues;
  getValue: (dotpath: string) => unknown;
  setValue: (dotpath: string, value: unknown) => void;
  reset: () => void;
  dirty: boolean;
  changedPaths: string[];
  changeCount: number;
};

/** Tracks a draft config + which leaf dotpaths differ from the original. */
export function useFormState(
  initial: ConfigValues,
  fieldPaths: string[],
): FormState {
  const [draft, setDraft] = useState<ConfigValues>(initial);

  const getValue = useCallback(
    (dotpath: string) => getAt(draft, dotpath),
    [draft],
  );

  const setValue = useCallback((dotpath: string, value: unknown) => {
    setDraft((d) => setAt(d, dotpath, value));
  }, []);

  const reset = useCallback(() => setDraft(initial), [initial]);

  const changedPaths = useMemo(
    () =>
      fieldPaths.filter(
        (p) => stableStringify(getAt(draft, p)) !== stableStringify(getAt(initial, p)),
      ),
    [draft, initial, fieldPaths],
  );

  return {
    draft,
    getValue,
    setValue,
    reset,
    dirty: changedPaths.length > 0,
    changedPaths,
    changeCount: changedPaths.length,
  };
}
