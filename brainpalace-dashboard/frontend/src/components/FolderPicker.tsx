import { useEffect, useRef, useState } from "react";
import { FolderPlus } from "lucide-react";

/** Curated file-type presets mirroring `brainpalace types` / server presets. */
export const TYPE_PRESETS = [
  "code",
  "docs",
  "python",
  "typescript",
  "javascript",
  "go",
  "rust",
  "java",
  "web",
  "text",
] as const;

export type AddFolderPayload = {
  folder_path: string;
  include_types: string[];
  watch_mode: string;
};

/**
 * Modal for adding a folder to the index. The folder path is necessarily a
 * free-text input; everything else (type preset, watch mode) is a dropdown.
 */
export function FolderPicker({
  open,
  busy = false,
  onAdd,
  onCancel,
}: {
  open: boolean;
  busy?: boolean;
  onAdd: (p: AddFolderPayload) => void;
  onCancel: () => void;
}) {
  const [path, setPath] = useState("");
  const [preset, setPreset] = useState<string>("code");
  const [watch, setWatch] = useState<string>("auto");
  const pathRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setPath("");
      setPreset("code");
      setWatch("auto");
      pathRef.current?.focus();
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;

  const submit = () => {
    const trimmed = path.trim();
    if (!trimmed) return;
    onAdd({ folder_path: trimmed, include_types: [preset], watch_mode: watch });
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4" role="presentation">
      <div
        className="absolute inset-0 bg-ink-900/70 backdrop-blur-sm"
        onClick={onCancel}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="h2-folderpicker-title"
        data-testid="folder-picker"
        className="panel animate-fade-up relative z-10 w-full max-w-lg p-6"
      >
        <div className="mb-5 flex items-start gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-accent/15 text-accent">
            <FolderPlus className="h-5 w-5" aria-hidden="true" />
          </span>
          <div>
            <h2
              id="h2-folderpicker-title"
              className="font-display text-base font-semibold tracking-tight"
            >
              Index a folder
            </h2>
            <p className="mt-1 text-sm text-fg-muted">
              Point at a directory and pick which file types to ingest.
            </p>
          </div>
        </div>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="input-folder-path"
              className="eyebrow"
            >
              Folder path
            </label>
            <input
              ref={pathRef}
              id="input-folder-path"
              data-testid="input-folder-path"
              type="text"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
              placeholder="/abs/path/to/folder"
              className="rounded-lg border border-line bg-ink-700/50 px-3 py-2 font-mono text-sm text-fg placeholder:text-fg-faint focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/30"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="select-folder-type" className="eyebrow">
                File types
              </label>
              <select
                id="select-folder-type"
                data-testid="select-folder-type"
                value={preset}
                onChange={(e) => setPreset(e.target.value)}
                className="rounded-lg border border-line bg-ink-700/50 px-3 py-2 text-sm text-fg focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/30"
              >
                {TYPE_PRESETS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="select-folder-watch" className="eyebrow">
                Watch mode
              </label>
              <select
                id="select-folder-watch"
                data-testid="select-folder-watch"
                value={watch}
                onChange={(e) => setWatch(e.target.value)}
                className="rounded-lg border border-line bg-ink-700/50 px-3 py-2 text-sm text-fg focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/30"
              >
                <option value="auto">auto (live re-index)</option>
                <option value="off">off</option>
              </select>
            </div>
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            data-testid="btn-folder-cancel"
            onClick={onCancel}
            disabled={busy}
            className="btn-ghost btn-sm"
          >
            Cancel
          </button>
          <button
            type="button"
            data-testid="btn-folder-add"
            onClick={submit}
            disabled={busy || !path.trim()}
            className="btn-primary btn-sm"
          >
            Add folder
          </button>
        </div>
      </div>
    </div>
  );
}
