import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { P95_SLO_MS } from "@/lib/utils";

export interface LatencyPercentiles {
  p50: number | null | undefined;
  p95: number | null | undefined;
  p99: number | null | undefined;
}

/**
 * p50/p95/p99 bars for a load run (the API returns aggregates, not a time
 * series), with the p95 SLO (200ms) reference line. Bars above the SLO go red.
 */
export function LatencyChart({ p50, p95, p99 }: LatencyPercentiles) {
  const data = [
    { label: "p50", ms: p50 ?? 0 },
    { label: "p95", ms: p95 ?? 0 },
    { label: "p99", ms: p99 ?? 0 },
  ];
  return (
    <div style={{ height: 260 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 20, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
          <XAxis dataKey="label" stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} />
          <YAxis
            stroke="hsl(var(--muted-foreground))"
            fontSize={12}
            tickLine={false}
            axisLine={false}
            unit="ms"
            width={56}
            tickCount={6}
            // Always include the SLO line, even when every percentile is ~0ms.
            domain={[0, (dataMax: number) => Math.ceil((Math.max(dataMax, P95_SLO_MS) * 1.1) / 50) * 50]}
          />
          <Tooltip
            contentStyle={{
              background: "hsl(var(--popover))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 8,
              fontSize: 12,
            }}
            formatter={(v) => [`${Math.round(Number(v))}ms`, "latency"]}
          />
          <ReferenceLine
            y={P95_SLO_MS}
            stroke="hsl(var(--gate-pass))"
            strokeDasharray="6 2"
            label={{ value: `p95 SLO ${P95_SLO_MS}ms`, position: "insideTopRight", offset: 6, fill: "hsl(var(--gate-pass))", fontSize: 12 }}
          />
          <Bar dataKey="ms" radius={[4, 4, 0, 0]}>
            {data.map((d) => (
              <Cell key={d.label} fill={d.ms > P95_SLO_MS ? "hsl(var(--gate-fail))" : "hsl(var(--gate-pass))"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
