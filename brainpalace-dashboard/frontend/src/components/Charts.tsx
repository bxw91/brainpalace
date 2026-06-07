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

/** Vertical bars of query volume per time bucket. */
export function VolumeChart({ data }: { data: TimeSeriesDatum[] }) {
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
}

/** Latency over time (ms) as a line. */
export function LatencyChart({ data }: { data: TimeSeriesDatum[] }) {
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
}

export type ChunkDatum = { name: string; chunks: number; reachable: boolean };

/** Horizontal bar of per-instance chunk counts. */
export function ChunkBarChart({ data }: { data: ChunkDatum[] }) {
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
}
