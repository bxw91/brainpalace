import type { ReactNode } from "react";

export type StatTone = "default" | "run" | "warn" | "idle" | "bad" | "accent";

const TONE: Record<StatTone, { value: string; chip: string }> = {
  default: { value: "text-fg", chip: "bg-ink-600 text-fg-muted" },
  run: { value: "text-run", chip: "bg-run/15 text-run" },
  warn: { value: "text-warn", chip: "bg-warn/15 text-warn" },
  idle: { value: "text-fg-muted", chip: "bg-ink-600 text-fg-muted" },
  bad: { value: "text-bad", chip: "bg-bad/15 text-bad" },
  accent: { value: "text-accent", chip: "bg-accent/15 text-accent" },
};

export function StatCard({
  testId,
  label,
  value,
  hint,
  icon,
  tone = "default",
  loading = false,
}: {
  testId?: string;
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon?: ReactNode;
  tone?: StatTone;
  loading?: boolean;
}) {
  const t = TONE[tone];
  return (
    <div
      data-testid={testId}
      className="panel panel-hover relative flex flex-col gap-3 overflow-hidden p-5"
    >
      <div className="flex items-center justify-between">
        <span className="eyebrow">{label}</span>
        {icon && (
          <span
            className={`grid h-7 w-7 place-items-center rounded-lg ${t.chip}`}
          >
            {icon}
          </span>
        )}
      </div>
      {loading ? (
        <div className="skeleton h-9 w-20" />
      ) : (
        <span
          className={`font-display text-3xl font-semibold tabular-nums tracking-tight ${t.value}`}
        >
          {value}
        </span>
      )}
      {hint && <span className="text-xs text-fg-faint">{hint}</span>}
    </div>
  );
}
