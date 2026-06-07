import { useEffect, useRef } from "react";
import { AlertTriangle } from "lucide-react";

export type ConfirmTone = "danger" | "default";

/**
 * Shared confirmation modal for destructive actions (Stop/Restart/Remove).
 * Rendered only when `open` is true; the parent owns the open state.
 */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "danger",
  onConfirm,
  onCancel,
  busy = false,
}: {
  open: boolean;
  title: string;
  message: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: ConfirmTone;
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
}) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) confirmRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onCancel();
        return;
      }
      if (e.key !== "Tab") return;
      // Trap focus inside the dialog (cycle between the focusable controls).
      const panel = panelRef.current;
      if (!panel) return;
      const focusable = panel.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      } else if (active && !panel.contains(active)) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center p-4"
      role="presentation"
    >
      <div
        className="absolute inset-0 bg-ink-900/70 backdrop-blur-sm"
        onClick={onCancel}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="h2-confirm-title"
        data-testid="confirm-dialog"
        className="panel animate-fade-up relative z-10 w-full max-w-md p-6"
      >
        <div className="flex items-start gap-3">
          {tone === "danger" && (
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-bad/15 text-bad">
              <AlertTriangle className="h-5 w-5" aria-hidden="true" />
            </span>
          )}
          <div className="min-w-0">
            <h2
              id="h2-confirm-title"
              className="font-display text-base font-semibold tracking-tight"
            >
              {title}
            </h2>
            <div className="mt-1 text-sm text-fg-muted">{message}</div>
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            data-testid="btn-cancel"
            onClick={onCancel}
            disabled={busy}
            className="btn-ghost btn-sm"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            data-testid="btn-confirm"
            onClick={onConfirm}
            disabled={busy}
            className={tone === "danger" ? "btn-danger btn-sm" : "btn-primary btn-sm"}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
