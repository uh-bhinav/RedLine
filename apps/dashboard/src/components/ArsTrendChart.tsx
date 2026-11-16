import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ArsSnapshotItem } from "@/lib/types";
import { ARS_TARGET } from "@/lib/utils";

// Categorical palette slots 1-4 (blue/orange/aqua/yellow). The composite ARS
// line is the summary line, styled in ink (foreground) rather than a series colour.
const SUB_SCORE_COLORS = {
  correctness: "#2a78d6",
  safety: "#eb6834",
  latency: "#1baf7a",
  cost: "#eda100",
} as const;

interface ChartPoint {
  created_at: string;
  correctness: number;
  safety: number;
  latency: number;
  cost: number;
  ars: number;
  version_label: string;
}

/** ARS composite + 4 sub-scores over time, with the 0.9 SLO target line. */
export function ArsTrendChart({ snapshots }: { snapshots: ArsSnapshotItem[] }) {
  if (snapshots.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        No ARS snapshots yet -- run an eval to populate the trend.
      </p>
    );
  }

  const data: ChartPoint[] = snapshots.map((s) => ({
    created_at: new Date(s.created_at).toLocaleDateString(),
    correctness: s.correctness,
    safety: s.safety,
    latency: s.latency,
    cost: s.cost,
    ars: s.ars,
    version_label: s.version_label,
  }));

  // Mark the x position of the first snapshot of each new version.
  const versionBoundaries = data
    .map((point, i) => (i === 0 || point.version_label !== data[i - 1].version_label ? point : null))
    .filter((p): p is ChartPoint => p !== null);

  const below = snapshots.filter((s) => s.ars < ARS_TARGET).length;

  return (
    <div className="space-y-2">
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
          <XAxis dataKey="created_at" tick={{ fontSize: 12 }} stroke="hsl(var(--muted-foreground))" />
          <YAxis
            domain={[0, 1]}
            ticks={[0, 0.25, 0.5, 0.7, 0.9, 1]}
            tick={{ fontSize: 12 }}
            stroke="hsl(var(--muted-foreground))"
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "hsl(var(--popover))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 8,
              fontSize: 12,
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <ReferenceLine
            y={ARS_TARGET}
            stroke="hsl(var(--gate-pass))"
            strokeDasharray="6 2"
            label={{
              value: "SLO Target 0.9",
              position: "insideBottomRight",
              fill: "hsl(var(--gate-pass))",
              fontSize: 11,
            }}
          />
          {versionBoundaries.map((point) => (
            <ReferenceLine
              key={point.created_at + point.version_label}
              x={point.created_at}
              stroke="hsl(var(--muted-foreground))"
              strokeDasharray="4 4"
              label={{ value: point.version_label, fontSize: 10, position: "top" }}
            />
          ))}
          <Line type="monotone" dataKey="correctness" stroke={SUB_SCORE_COLORS.correctness} strokeWidth={2} dot={{ r: 3 }} />
          <Line type="monotone" dataKey="safety" stroke={SUB_SCORE_COLORS.safety} strokeWidth={2} dot={{ r: 3 }} />
          <Line type="monotone" dataKey="latency" stroke={SUB_SCORE_COLORS.latency} strokeWidth={2} dot={{ r: 3 }} />
          <Line type="monotone" dataKey="cost" stroke={SUB_SCORE_COLORS.cost} strokeWidth={2} dot={{ r: 3 }} />
          <Line
            type="monotone"
            dataKey="ars"
            name="ARS (composite)"
            stroke="hsl(var(--foreground))"
            strokeWidth={3}
            dot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>
      <p
        className={
          below > 0
            ? "text-sm font-medium text-amber-600 dark:text-amber-400"
            : "text-sm text-muted-foreground"
        }
      >
        ARS has been below target for {below} of the last {snapshots.length} runs
      </p>
    </div>
  );
}
