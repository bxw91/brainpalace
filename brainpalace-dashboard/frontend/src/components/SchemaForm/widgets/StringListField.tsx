import { Plus, X } from "lucide-react";

/**
 * String-list editor (e.g. `git_indexing.path_filter`). One input per row; the
 * emitted value is an array of non-empty strings, or `undefined` when empty so
 * an untouched/cleared field is omitted from the saved config.
 */
export function StringListField({
  dotpath,
  value,
  onChange,
}: {
  dotpath: string;
  value?: string[];
  onChange: (v: string[] | undefined) => void;
}) {
  const items = value ?? [];

  const emit = (next: string[]) => {
    const cleaned = next.filter((s) => s.trim() !== "");
    onChange(cleaned.length === 0 ? undefined : cleaned);
  };
  // Keep blank in-progress rows visible while editing; only prune on emit.
  const update = (idx: number, val: string) => {
    const next = [...items];
    next[idx] = val;
    emit(next);
  };
  const remove = (idx: number) => emit(items.filter((_, i) => i !== idx));
  const add = () => onChange([...items, ""]);

  return (
    <div data-testid={`stringlist-${dotpath}`} className="flex flex-col gap-2">
      {items.map((s, idx) => (
        <div key={idx} className="flex items-center gap-2">
          <input
            data-testid={`stringlist-item-${dotpath}-${idx}`}
            type="text"
            value={s}
            placeholder="value"
            onChange={(e) => update(idx, e.target.value)}
            className="flex-1 rounded-lg border border-line bg-ink-900/50 px-3 py-2 text-sm text-fg outline-none transition-colors placeholder:text-fg-faint focus:border-accent/50 focus:ring-2 focus:ring-accent/30"
          />
          <button
            type="button"
            aria-label="Remove"
            data-testid={`stringlist-remove-${dotpath}-${idx}`}
            onClick={() => remove(idx)}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line text-fg-muted transition-colors hover:bg-ink-700/60 hover:text-fg focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      ))}
      <button
        type="button"
        data-testid={`stringlist-add-${dotpath}`}
        onClick={add}
        className="btn-ghost btn-sm self-start"
      >
        <Plus className="h-3.5 w-3.5" aria-hidden="true" />
        Add item
      </button>
    </div>
  );
}
