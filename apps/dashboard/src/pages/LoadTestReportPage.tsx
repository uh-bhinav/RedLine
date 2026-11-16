import { useParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Skeleton } from "@/components/ui/skeleton";
import { useLoadRunDetail } from "@/hooks/useLoadRuns";

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}

export function LoadTestReportPage() {
  const { loadRunId } = useParams<{ loadRunId: string }>();
  const { data: run, isLoading, error } = useLoadRunDetail(loadRunId);

  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error || !run) {
    return (
      <p className="text-sm text-destructive">
        Failed to load report: {error?.message ?? "not found"}
      </p>
    );
  }

  const isActive = run.status === "pending" || run.status === "running";
  const percentileData = [
    { name: "p50", ms: run.p50_latency_ms ?? 0 },
    { name: "p95", ms: run.p95_latency_ms ?? 0 },
    { name: "p99", ms: run.p99_latency_ms ?? 0 },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="font-mono text-lg font-semibold">{run.id}</h1>
        <span className="text-sm text-muted-foreground">
          {run.status}
          {isActive && " (refreshing…)"}
        </span>
      </div>

      {run.error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm">
          {run.error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatTile
          label="Requests"
          value={`${run.successful_requests ?? 0}/${run.total_requests ?? 0}`}
        />
        <StatTile
          label="Error rate"
          value={run.error_rate != null ? `${(run.error_rate * 100).toFixed(1)}%` : "—"}
        />
        <StatTile
          label="Cost/hour"
          value={run.cost_per_hour_usd != null ? `$${run.cost_per_hour_usd.toFixed(2)}` : "—"}
        />
        <StatTile
          label="Throughput"
          value={run.throughput_rps != null ? `${run.throughput_rps.toFixed(1)} req/s` : "—"}
        />
      </div>

      <div>
        <h2 className="mb-2 text-sm font-medium text-muted-foreground">Latency percentiles</h2>
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={percentileData} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis dataKey="name" tick={{ fontSize: 12 }} stroke="hsl(var(--muted-foreground))" />
            <YAxis tick={{ fontSize: 12 }} stroke="hsl(var(--muted-foreground))" unit="ms" />
            <Tooltip
              contentStyle={{
                backgroundColor: "hsl(var(--popover))",
                border: "1px solid hsl(var(--border))",
                borderRadius: 8,
                fontSize: 12,
              }}
            />
            <Bar dataKey="ms" fill="#2a78d6" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
