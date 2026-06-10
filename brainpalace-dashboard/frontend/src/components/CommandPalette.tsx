import { useEffect, useMemo, useRef, useState } from "react";
import { TABS } from "../router";

/**
 * Keyboard-first navigation: Cmd/Ctrl+K opens, type to filter tabs,
 * Enter jumps. Navigation is injected (`onNavigate`) so the shell wires it
 * to the router and tests pass a spy.
 */
export function CommandPalette({
  onNavigate,
}: {
  onNavigate: (path: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  // Remember what had focus before the palette opened, so we can restore it
  // on close (mirrors the modal-dialog focus discipline in ConfirmDialog).
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
        setFilter("");
        setCursor(0);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) {
      restoreFocusRef.current =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
      inputRef.current?.focus();
    } else {
      // Return focus to whatever was focused before the palette opened.
      restoreFocusRef.current?.focus();
      restoreFocusRef.current = null;
    }
  }, [open]);

  const hits = useMemo(() => {
    const f = filter.trim().toLowerCase();
    return TABS.filter(
      (t) => !f || t.label.toLowerCase().includes(f) || t.path.includes(f),
    );
  }, [filter]);

  if (!open) return null;

  const go = (path: string) => {
    setOpen(false);
    onNavigate(path);
  };

  return (
    <div
      data-testid="command-palette"
      className="fixed inset-0 z-50 flex items-start justify-center pt-24"
      role="presentation"
    >
      <div
        className="absolute inset-0 bg-black/50"
        onClick={() => setOpen(false)}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Jump to"
        className="relative z-10 w-full max-w-md rounded-xl border border-line bg-ink-900 p-3 shadow-2xl"
      >
        <label htmlFor="palette-input" className="sr-only">
          Jump to
        </label>
        <input
          ref={inputRef}
          id="palette-input"
          data-testid="palette-input"
          type="text"
          value={filter}
          placeholder="Jump to…"
          onChange={(e) => {
            setFilter(e.target.value);
            setCursor(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setCursor((c) => Math.min(c + 1, hits.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setCursor((c) => Math.max(c - 1, 0));
            } else if (e.key === "Enter" && hits[cursor]) {
              go(hits[cursor].path);
            }
          }}
          className="w-full rounded-lg border border-line bg-ink-700/50 px-3 py-2 text-sm text-fg outline-none placeholder:text-fg-faint focus:border-accent/50 focus:ring-2 focus:ring-accent/30"
        />
        <ul className="mt-2 flex max-h-72 flex-col gap-0.5 overflow-y-auto">
          {hits.map((t, i) => (
            <li key={t.path}>
              <button
                type="button"
                onClick={() => go(t.path)}
                className={`w-full rounded-lg px-3 py-1.5 text-left text-sm ${
                  i === cursor ? "bg-accent/15 text-accent" : "text-fg-muted"
                }`}
              >
                {t.label}
                <span className="ml-2 font-mono text-[0.65rem] text-fg-faint">
                  {t.path}
                </span>
              </button>
            </li>
          ))}
          {hits.length === 0 && (
            <li className="px-3 py-1.5 text-sm text-fg-faint">No matches.</li>
          )}
        </ul>
      </div>
    </div>
  );
}
