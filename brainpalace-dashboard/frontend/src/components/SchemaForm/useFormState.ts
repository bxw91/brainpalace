import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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

/**
 * Drop `undefined` leaves and the empty parent blocks they leave behind. This
 * turns "revert to inherited" (staged as `setValue(path, undefined)`) into an
 * OMITTED key — the sparse payload the Save sends, where an absent key means
 * "inherit". Arrays and `null` are kept verbatim (a real, set value).
 */
function prune(obj: ConfigValues): ConfigValues {
  const out: ConfigValues = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v && typeof v === "object" && !Array.isArray(v)) {
      const pv = prune(v as ConfigValues);
      if (Object.keys(pv).length > 0) out[k] = pv;
    } else if (v !== undefined) {
      out[k] = v;
    }
  }
  return out;
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
  /** Sparse override set to PATCH (pruned of inherited/undefined keys). */
  draft: ConfigValues;
  getValue: (dotpath: string) => unknown;
  setValue: (dotpath: string, value: unknown) => void;
  /** Revert a key to its inherited value (staged; persists only on Save). */
  inherit: (dotpath: string) => void;
  reset: () => void;
  dirty: boolean;
  changedPaths: string[];
  changeCount: number;
  /** Keys set in the loaded config that the draft reverts → Save `unset` list. */
  unsetPaths: string[];
};

/**
 * Tracks a draft config + which leaf dotpaths differ from the loaded server
 * state. "Override" = a value in the draft; "inherit" = `undefined` in the draft
 * (pruned out of the payload, and reported in `unsetPaths` when the loaded
 * config had set it). Everything — dirty count, the Save value set, the Save
 * unset list, and Discard — derives from comparing the pruned draft to
 * `initial`, so there is no hidden per-field mode to drift out of sync.
 */
export function useFormState(
  initial: ConfigValues,
  fieldPaths: string[],
): FormState {
  const [draft, setDraft] = useState<ConfigValues>(initial);

  // Resync to server truth when a NEW snapshot loads (after a Save/refetch),
  // but never clobber unsaved edits on an incidental refetch (window focus): a
  // post-Save refetch leaves the draft already equal to the server, so the
  // dirty guard lets it through; a focus refetch with pending edits is skipped.
  const initialRef = useRef(initial);
  const dirtyRef = useRef(false);
  useEffect(() => {
    if (initialRef.current !== initial) {
      const wasDirty = dirtyRef.current;
      initialRef.current = initial;
      if (!wasDirty) setDraft(initial);
    }
  }, [initial]);

  const getValue = useCallback(
    (dotpath: string) => getAt(draft, dotpath),
    [draft],
  );

  const setValue = useCallback((dotpath: string, value: unknown) => {
    setDraft((d) => setAt(d, dotpath, value));
  }, []);

  const inherit = useCallback((dotpath: string) => {
    setDraft((d) => setAt(d, dotpath, undefined));
  }, []);

  const reset = useCallback(() => setDraft(initialRef.current), []);

  const cleaned = useMemo(() => prune(draft), [draft]);

  const changedPaths = useMemo(
    () =>
      fieldPaths.filter(
        (p) =>
          stableStringify(getAt(cleaned, p)) !==
          stableStringify(getAt(initial, p)),
      ),
    [cleaned, initial, fieldPaths],
  );

  const unsetPaths = useMemo(
    () =>
      fieldPaths.filter(
        (p) =>
          getAt(initial, p) !== undefined && getAt(cleaned, p) === undefined,
      ),
    [cleaned, initial, fieldPaths],
  );

  dirtyRef.current = changedPaths.length > 0;

  return {
    draft: cleaned,
    getValue,
    setValue,
    inherit,
    reset,
    dirty: changedPaths.length > 0,
    changedPaths,
    changeCount: changedPaths.length,
    unsetPaths,
  };
}
