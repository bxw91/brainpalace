import { useState } from "react";
import { Plus, X } from "lucide-react";

/**
 * Key/value editor for a free-form `dict[str, scalar]` (e.g. provider
 * `*.params`). Rows are held in local component state so blank/in-progress rows
 * stay visible while editing (an empty key can't be represented in the emitted
 * object). The cleaned object is pushed up on every change; an editor with no
 * non-empty keys emits `undefined` so an untouched/cleared field is omitted from
 * the saved config.
 */
export function DictField({
  dotpath,
  value,
  onChange,
}: {
  dotpath: string;
  value?: Record<string, unknown>;
  onChange: (v: Record<string, unknown> | undefined) => void;
}) {
  const [rows, setRows] = useState<[string, string][]>(() =>
    Object.entries(value ?? {}).map(([k, v]) => [k, String(v ?? "")]),
  );

  const sync = (next: [string, string][]) => {
    setRows(next);
    const obj: Record<string, unknown> = {};
    for (const [k, v] of next) if (k.trim() !== "") obj[k] = v;
    onChange(Object.keys(obj).length === 0 ? undefined : obj);
  };

  const setKey = (idx: number, key: string) =>
    sync(rows.map((r, i) => (i === idx ? [key, r[1]] : r)));
  const setVal = (idx: number, val: string) =>
    sync(rows.map((r, i) => (i === idx ? [r[0], val] : r)));
  const remove = (idx: number) => sync(rows.filter((_, i) => i !== idx));
  const add = () => sync([...rows, ["", ""]]);

  return (
    <div data-testid={`dict-${dotpath}`} className="flex flex-col gap-2">
      {rows.map(([k, v], idx) => (
        <div key={idx} className="flex items-center gap-2">
          <input
            data-testid={`dict-key-${dotpath}-${idx}`}
            type="text"
            value={k}
            placeholder="key"
            onChange={(e) => setKey(idx, e.target.value)}
            className="w-40 rounded-lg border border-line bg-ink-900/50 px-3 py-2 text-sm text-fg outline-none transition-colors placeholder:text-fg-faint focus:border-accent/50 focus:ring-2 focus:ring-accent/30"
          />
          <input
            data-testid={`dict-val-${dotpath}-${idx}`}
            type="text"
            value={v}
            placeholder="value"
            onChange={(e) => setVal(idx, e.target.value)}
            className="flex-1 rounded-lg border border-line bg-ink-900/50 px-3 py-2 text-sm text-fg outline-none transition-colors placeholder:text-fg-faint focus:border-accent/50 focus:ring-2 focus:ring-accent/30"
          />
          <button
            type="button"
            aria-label="Remove"
            data-testid={`dict-remove-${dotpath}-${idx}`}
            onClick={() => remove(idx)}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line text-fg-muted transition-colors hover:bg-ink-700/60 hover:text-fg focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      ))}
      <button
        type="button"
        data-testid={`dict-add-${dotpath}`}
        onClick={add}
        className="btn-ghost btn-sm self-start"
      >
        <Plus className="h-3.5 w-3.5" aria-hidden="true" />
        Add entry
      </button>
    </div>
  );
}
