import { Gauge } from "lucide-react";
import { Link } from "react-router-dom";
import { EmptyState } from "@/components/EmptyState";
import { ErrorCard } from "@/components/ErrorCard";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAllLoadRuns, useLoadRuns } from "@/hooks/useLoadRuns";
import { cn, formatCost, formatMs, formatPct, shortId, timeAgo } from "@/lib/utils";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
}

/** Load tests tab: latest-run summary panel above the per-agent run table. */
export function LoadTestsTab({
  agentId,
  trigger,
}: {
  agentId: string;
  trigger?: React.ReactNode;
}) {
  const runs = useLoadRuns(agentId);
  const all = useAllLoadRuns();

  if (runs.isLoading) return <Skeleton className="h-40 w-full" />;
  if (runs.error) return <ErrorCard error={runs.error} onRetry={() => void runs.refetch()} />;

  const rows = runs.data ?? [];
  if (rows.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={Gauge}
          title="No load tests yet"
          description="Run a load test to see p95 latency, error rate and projected cost at scale."
          action={trigger}
        />
      </Card>
    );
  }

  const latestDetail = (all.data ?? [])
    .filter((r) => r.agent_id === agentId && r.status === "completed")
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const latestSummary = rows.find((r) => r.status === "completed") ?? rows[0];
  const cph = latestSummary.cost_per_hour_usd;
  const viable = cph != null && cph * 10 <= 10;

  return (
    <div className="space-y-4">
      <Card className="space-y-3 p-4">
        <div className="text-sm font-medium">
          Latest load test ({timeAgo(latestSummary.completed_at ?? latestSummary.started_at)})
          <span className="text-muted-foreground">
            {" "}
            &middot; {latestSummary.concurrency} concurrent users &middot;{" "}
            {latestSummary.duration_seconds} seconds
          </span>
        </div>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="p95" value={formatMs(latestSummary.p95_latency_ms)} />
          <Stat label="Error rate" value={formatPct(latestSummary.error_rate, 1)} />
          <Stat label="Cost/hour" value={formatCost(cph)} />
          <Stat
            label="Throughput"
            value={
              latestDetail?.throughput_rps != null
                ? `${latestDetail.throughput_rps.toFixed(1)} req/s`
                : "—"
            }
          />
        </div>
        {cph != null && (
          <p
            className={cn(
              "text-sm font-medium",
              viable ? "text-green-600 dark:text-green-400" : "text-amber-600 dark:text-amber-400",
            )}
          >
            {viable
              ? "● Financially viable at current scale"
              : `○ Review before exceeding ${latestSummary.concurrency} concurrent users`}
          </p>
        )}
      </Card>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Run</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Users</TableHead>
            <TableHead>p95</TableHead>
            <TableHead>Error rate</TableHead>
            <TableHead>Cost/hour</TableHead>
            <TableHead>When</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((run) => (
            <TableRow key={run.id}>
              <TableCell>
                <Link to={`/load-run/${run.id}`} className="font-mono text-xs hover:underline">
                  {shortId(run.id)}
                </Link>
              </TableCell>
              <TableCell>
                <Badge
                  variant={
                    run.status === "completed" ? "pass" : run.status === "failed" ? "fail" : "warn"
                  }
                >
                  {run.status}
                </Badge>
              </TableCell>
              <TableCell>{run.concurrency}</TableCell>
              <TableCell>{formatMs(run.p95_latency_ms)}</TableCell>
              <TableCell>{formatPct(run.error_rate, 1)}</TableCell>
              <TableCell>{formatCost(run.cost_per_hour_usd)}</TableCell>
              <TableCell className="text-muted-foreground">
                {timeAgo(run.completed_at ?? run.started_at)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
