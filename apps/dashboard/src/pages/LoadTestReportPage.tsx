import { Loader2, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { useParams } from "react-router-dom";
import { CostViabilityCard } from "@/components/CostViabilityCard";
import { ErrorCard } from "@/components/ErrorCard";
import { LatencyChart } from "@/components/LatencyChart";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useLoadRunDetail } from "@/hooks/useLoadRuns";
import { ACTIVE_STATUSES, cn, formatCost, formatDateTime, P95_SLO_MS, shortId } from "@/lib/utils";

function StatTile({
  label,
  value,
  note,
  good,
}: {
  label: string;
  value: ReactNode;
  note?: string;
  good?: boolean;
}) {
  return (
    <div className="min-w-0 rounded-lg border p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="break-words text-xl font-semibold tabular-nums sm:text-2xl">{value}</div>
      {note && (
        <div
          className={cn(
            "mt-1 text-xs",
            good === undefined
              ? "text-muted-foreground"
              : good
                ? "text-green-600 dark:text-green-400"
                : "text-amber-600 dark:text-amber-400",
          )}
        >
          {note}
        </div>
      )}
    </div>
  );
}

export function LoadTestReportPage() {
  const { loadRunId } = useParams<{ loadRunId: string }>();
  const { data: run, isLoading, error, refetch } = useLoadRunDetail(loadRunId);
  useDocumentTitle(`Load Test - ${loadRunId ? shortId(loadRunId) : ""}`);

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error || !run) {
    return <ErrorCard error={error ?? new Error("Load run not found")} onRetry={() => void refetch()} />;
  }

  const isActive = ACTIVE_STATUSES.has(run.status);
  const isFailed = run.status === "failed";
  const hasResults = run.status === "completed";

  const errOk = run.error_rate != null && run.error_rate <= 0.01;
  const costOk = run.cost_per_hour_usd != null && run.cost_per_hour_usd * 10 <= 10;
  const rps = run.throughput_rps;
  const p95Over = run.p95_latency_ms != null && run.p95_latency_ms > P95_SLO_MS;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">Load Test Report</h1>
          <p className="text-sm text-muted-foreground">
            <span className="font-mono">{shortId(run.id)}</span> - {run.concurrency} virtual users for{" "}
            {run.duration_seconds}s - triggered by {run.triggered_by}
            {run.completed_at ? ` - finished ${formatDateTime(run.completed_at)}` : ""}
          </p>
        </div>
        {isActive ? (
          <Badge variant="warn">
            <Loader2 className="size-3 animate-spin" />
            {run.status === "running" ? "RUNNING" : "QUEUED"}
          </Badge>
        ) : isFailed ? (
          <Badge variant="fail">
            <XCircle className="size-3" />
            FAILED
          </Badge>
        ) : (
          <Badge variant="pass">COMPLETED</Badge>
        )}
      </div>

      {isActive && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
          <Loader2 className="size-4 animate-spin" />
          Load test in progress. This page refreshes automatically every few seconds.
        </div>
      )}

      {isFailed && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-700 dark:text-red-300">
          <div className="font-medium">Load test failed</div>
          <div className="mt-1 break-words">{run.error ?? "No error detail was recorded."}</div>
        </div>
      )}

      {hasResults && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatTile
              label="Requests"
              value={`${run.successful_requests ?? 0}/${run.total_requests ?? 0}`}
              note="successful / total"
            />
            <StatTile
              label="Error rate"
              value={run.error_rate != null ? `${(run.error_rate * 100).toFixed(1)}%` : "-"}
              note={
                run.error_rate == null
                  ? undefined
                  : errOk
                    ? "✓ Within acceptable bounds"
                    : "⚠ Above 1% threshold"
              }
              good={run.error_rate == null ? undefined : errOk}
            />
            <StatTile
              label="Cost/hour"
              value={formatCost(run.cost_per_hour_usd)}
              note={
                run.cost_per_hour_usd == null
                  ? undefined
                  : costOk
                    ? "✓ Viable at current scale"
                    : "⚠ High - review before scaling"
              }
              good={run.cost_per_hour_usd == null ? undefined : costOk}
            />
            <StatTile
              label="Throughput"
              value={rps != null ? `${rps.toFixed(1)} req/s` : "-"}
              note={
                rps != null
                  ? `${rps.toFixed(1)} req/s ~ ${Math.round(rps * 3600).toLocaleString()} req/hour capacity`
                  : undefined
              }
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Latency percentiles{" "}
                {p95Over && (
                  <span className="ml-2 text-sm font-normal text-red-600 dark:text-red-400">
                    p95 exceeds the {P95_SLO_MS}ms SLO
                  </span>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <LatencyChart p50={run.p50_latency_ms} p95={run.p95_latency_ms} p99={run.p99_latency_ms} />
            </CardContent>
          </Card>

          <CostViabilityCard costPerHourUsd={run.cost_per_hour_usd} concurrency={run.concurrency} />
        </>
      )}
    </div>
  );
}
