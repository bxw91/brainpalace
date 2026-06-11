import { memo } from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
} from "recharts";

const TOOLTIP_STYLE = {
  background: "#0b1118",
  border: "1px solid #1e2c3a",
  borderRadius: 10,
  color: "#e6edf3",
  fontSize: 12,
} as const;

export type TimeSeriesDatum = { label: string; value: number };

/** Vertical bars of query volume per time bucket.
 *  memo'd: the dashboard polls on an interval, so the parent re-renders often;
 *  recharts measure/animation passes are expensive, so skip them when data is
 *  referentially unchanged. */
export const VolumeChart = memo(function VolumeChart({
  data,
}: {
  data: TimeSeriesDatum[];
}) {
  if (data.length === 0) {
    return (
      <p className="px-1 py-8 text-center text-sm text-fg-faint">
        No queries in this window.
      </p>
    );
  }
  return (
    <div data-testid="volume-chart" style={{ width: "100%", height: 180 }}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
          <XAxis
            dataKey="label"
            tick={{ fill: "#5f7488", fontSize: 10 }}
            axisLine={{ stroke: "#1e2c3a" }}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            allowDecimals={false}
            tick={{ fill: "#5f7488", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={28}
          />
          <Tooltip cursor={{ fill: "rgba(45,212,191,0.06)" }} contentStyle={TOOLTIP_STYLE} />
          <Bar dataKey="value" radius={[4, 4, 0, 0]} barSize={18} fill="#2dd4bf" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
});

/** Latency over time (ms) as a line. */
export const LatencyChart = memo(function LatencyChart({
  data,
}: {
  data: TimeSeriesDatum[];
}) {
  if (data.length === 0) {
    return (
      <p className="px-1 py-8 text-center text-sm text-fg-faint">
        No latency samples in this window.
      </p>
    );
  }
  return (
    <div data-testid="latency-chart" style={{ width: "100%", height: 180 }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
          <XAxis
            dataKey="label"
            tick={{ fill: "#5f7488", fontSize: 10 }}
            axisLine={{ stroke: "#1e2c3a" }}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fill: "#5f7488", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={36}
            unit="ms"
          />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Line
            type="monotone"
            dataKey="value"
            stroke="#38bdf8"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: "#38bdf8" }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
});

/** Single-line percentage trend (0–100), used for cache hit-rate over time. */
export const RateChart = memo(function RateChart({
  data,
}: {
  data: TimeSeriesDatum[];
}) {
  if (data.length < 2) {
    return (
      <p className="px-1 py-8 text-center text-sm text-fg-faint">
        Not enough snapshots yet — points accrue every ~5 minutes while the
        dashboard is open.
      </p>
    );
  }
  return (
    <div data-testid="rate-chart" style={{ width: "100%", height: 180 }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
          <XAxis
            dataKey="label"
            tick={{ fill: "#5f7488", fontSize: 10 }}
            axisLine={{ stroke: "#1e2c3a" }}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[0, 100]}
            tick={{ fill: "#5f7488", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={32}
          />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Line dataKey="value" stroke="#2dd4bf" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
});

export type PercentileDatum = { label: string; p50: number; p95: number };

/** Dual-line p50/p95 latency trend. memo'd for the same reason as VolumeChart. */
export const PercentileChart = memo(function PercentileChart({
  data,
}: {
  data: PercentileDatum[];
}) {
  if (data.length === 0) {
    return (
      <p className="px-1 py-8 text-center text-sm text-fg-faint">
        No queries in this window.
      </p>
    );
  }
  return (
    <div data-testid="percentile-chart" style={{ width: "100%", height: 180 }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
          <XAxis
            dataKey="label"
            tick={{ fill: "#5f7488", fontSize: 10 }}
            axisLine={{ stroke: "#1e2c3a" }}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fill: "#5f7488", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={36}
          />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(v: number | string) => `${Math.round(Number(v))} ms`}
          />
          <Line dataKey="p50" stroke="#2dd4bf" dot={false} strokeWidth={2} />
          <Line dataKey="p95" stroke="#f59e0b" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
});

export type ChunkDatum = { name: string; chunks: number; reachable: boolean };

/** Horizontal bar of per-instance chunk counts. */
export const ChunkBarChart = memo(function ChunkBarChart({
  data,
}: {
  data: ChunkDatum[];
}) {
  if (data.length === 0) {
    return (
      <p className="px-1 py-8 text-center text-sm text-fg-faint">
        No indexed instances to chart yet.
      </p>
    );
  }
  return (
    <div data-testid="chunk-chart" style={{ width: "100%", height: 32 + data.length * 40 }}>
      <ResponsiveContainer>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 16, bottom: 4, left: 8 }}
        >
          <XAxis
            type="number"
            tick={{ fill: "#5f7488", fontSize: 11 }}
            axisLine={{ stroke: "#1e2c3a" }}
            tickLine={false}
          />
          <YAxis
            type="category"
            dataKey="name"
            width={110}
            tick={{ fill: "#9bb0c3", fontSize: 12 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            cursor={{ fill: "rgba(45,212,191,0.06)" }}
            contentStyle={{
              background: "#0b1118",
              border: "1px solid #1e2c3a",
              borderRadius: 10,
              color: "#e6edf3",
              fontSize: 12,
            }}
          />
          <Bar dataKey="chunks" radius={[0, 6, 6, 0]} barSize={18}>
            {data.map((d) => (
              <Cell key={d.name} fill={d.reachable ? "#2dd4bf" : "#27384b"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
});
