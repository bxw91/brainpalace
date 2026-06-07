import { memo } from "react";
import {
  ResponsiveContainer,
  RadialBarChart,
  RadialBar,
  PolarAngleAxis,
} from "recharts";

/**
 * Radial gauge of a 0–1 hit-rate. Colour shifts warn→run as the rate climbs.
 * memo'd: the cache tab polls, so re-render only when `rate` actually changes.
 */
export const HitRateGauge = memo(function HitRateGauge({
  rate,
}: {
  rate: number;
}) {
  const pct = Math.max(0, Math.min(100, Math.round(rate * 100)));
  const color = pct >= 75 ? "#34d399" : pct >= 40 ? "#fbbf24" : "#fb7185";
  const data = [{ name: "hit", value: pct, fill: color }];

  return (
    <div
      data-testid="hit-rate-gauge"
      data-rate={pct}
      className="relative"
      style={{ width: "100%", height: 180 }}
    >
      <ResponsiveContainer>
        <RadialBarChart
          innerRadius="72%"
          outerRadius="100%"
          data={data}
          startAngle={90}
          endAngle={-270}
        >
          <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
          <RadialBar background={{ fill: "#16212e" }} dataKey="value" cornerRadius={12} />
        </RadialBarChart>
      </ResponsiveContainer>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <span
          className="font-display text-3xl font-semibold tabular-nums tracking-tight"
          style={{ color }}
        >
          {pct}%
        </span>
        <span className="eyebrow mt-1">hit rate</span>
      </div>
    </div>
  );
});
