import { Minus, Plus } from "lucide-react";

function clamp(n: number, min?: number, max?: number): number {
  if (min !== undefined && n < min) return min;
  if (max !== undefined && n > max) return max;
  return n;
}

export function IntField({
  dotpath,
  value,
  onChange,
  min,
  max,
  step = 1,
}: {
  dotpath: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  const set = (n: number) => onChange(clamp(n, min, max));
  const atMin = min !== undefined && value <= min;
  const atMax = max !== undefined && value >= max;

  return (
    <div
      data-testid={`int-${dotpath}`}
      className="inline-flex items-center overflow-hidden rounded-lg border border-line bg-ink-900/50"
    >
      <button
        type="button"
        aria-label="Decrease"
        data-testid={`int-dec-${dotpath}`}
        disabled={atMin}
        onClick={() => set(value - step)}
        className="grid h-9 w-9 place-items-center text-fg-muted transition-colors hover:bg-ink-700/60 hover:text-fg focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/60 disabled:cursor-not-allowed disabled:opacity-30"
      >
        <Minus className="h-4 w-4" aria-hidden="true" />
      </button>
      <output
        data-testid={`int-value-${dotpath}`}
        className="min-w-[3rem] border-x border-line px-3 text-center font-mono text-sm tabular-nums text-fg"
      >
        {value}
      </output>
      <button
        type="button"
        aria-label="Increase"
        data-testid={`int-inc-${dotpath}`}
        disabled={atMax}
        onClick={() => set(value + step)}
        className="grid h-9 w-9 place-items-center text-fg-muted transition-colors hover:bg-ink-700/60 hover:text-fg focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/60 disabled:cursor-not-allowed disabled:opacity-30"
      >
        <Plus className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}
