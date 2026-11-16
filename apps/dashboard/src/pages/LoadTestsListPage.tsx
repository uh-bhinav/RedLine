import { Gauge } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { EmptyState } from "@/components/EmptyState";
import { ErrorCard } from "@/components/ErrorCard";
import { GateBadge } from "@/components/GateBadge";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useAllLoadRuns } from "@/hooks/useLoadRuns";
import { cn, formatCost, formatMs, formatPct, P95_SLO_MS, timeAgo } from "@/lib/utils";

export function LoadTestsListPage() {
  useDocumentTitle("Load Tests");
  const { data, isLoading, error, refetch } = useAllLoadRuns();
  const navigate = useNavigate();

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Load Tests</h1>
        <p className="text-sm text-muted-foreground">
          Latency, error rate and cost per hour for every load run across your agents.
        </p>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : error ? (
        <ErrorCard error={error} onRetry={() => void refetch()} />
      ) : !data || data.length === 0 ? (
        <EmptyState
          icon={Gauge}
          title="No load tests yet"
          description='Open an agent and use "Load" to run the first one.'
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Agent</TableHead>
                <TableHead>Version</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Users</TableHead>
                <TableHead className="text-right">p95</TableHead>
                <TableHead className="text-right">Error rate</TableHead>
                <TableHead className="text-right">Cost/hour</TableHead>
                <TableHead>When</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((r) => (
                <TableRow
                  key={r.id}
                  className="cursor-pointer"
                  onClick={() => navigate(`/load-run/${r.id}`)}
                >
                  <TableCell className="font-medium">
                    <Link
                      to={`/load-run/${r.id}`}
                      className="hover:underline"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {r.agent_name}
                    </Link>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{r.version_label}</TableCell>
                  <TableCell>
                    {r.status === "completed" ? (
                      <Badge variant="pass">COMPLETED</Badge>
                    ) : (
                      <GateBadge passed={null} status={r.status} />
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{r.concurrency}</TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      r.p95_latency_ms != null && r.p95_latency_ms > P95_SLO_MS && "text-red-600 dark:text-red-400",
                    )}
                  >
                    {formatMs(r.p95_latency_ms)}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      r.error_rate != null && r.error_rate > 0.01 && "text-amber-600 dark:text-amber-400",
                    )}
                  >
                    {formatPct(r.error_rate, 1)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{formatCost(r.cost_per_hour_usd)}</TableCell>
                  <TableCell className="whitespace-nowrap text-muted-foreground">
                    {timeAgo(r.created_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
