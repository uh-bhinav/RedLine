import { ListChecks } from "lucide-react";
import { Link } from "react-router-dom";
import { EmptyState } from "@/components/EmptyState";
import { ErrorCard } from "@/components/ErrorCard";
import { GateBadge } from "@/components/GateBadge";
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
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useRuns } from "@/hooks/useRuns";
import { arsColor, cn, formatAr, formatDateTime, shortId, timeAgo } from "@/lib/utils";

export function EvalRunsListPage() {
  useDocumentTitle("Eval Runs");
  const { data: runs, isLoading, error, refetch } = useRuns();

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Eval Runs</h1>
        <p className="text-sm text-muted-foreground">Every eval run across your agents.</p>
      </div>

      {isLoading && <Skeleton className="h-48 w-full" />}
      {error && <ErrorCard error={error} onRetry={() => void refetch()} />}

      {runs && runs.length === 0 && (
        <Card>
          <EmptyState
            icon={ListChecks}
            title="No eval runs yet"
            description="Open an agent and trigger an eval run to see it here."
            action={
              <Link to="/agent" className="text-sm font-medium text-primary hover:underline">
                Go to agents
              </Link>
            }
          />
        </Card>
      )}

      {runs && runs.length > 0 && (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Run</TableHead>
                <TableHead>Agent</TableHead>
                <TableHead>Version</TableHead>
                <TableHead>Suite</TableHead>
                <TableHead>Gate</TableHead>
                <TableHead>ARS</TableHead>
                <TableHead>Trigger</TableHead>
                <TableHead>When</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.map((r) => (
                <TableRow key={r.id}>
                  <TableCell>
                    <Link to={`/runs/${r.id}`} className="font-mono text-xs hover:underline">
                      {shortId(r.id)}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Link to={`/agent/${r.agent_id}`} className="font-medium hover:underline">
                      {r.agent_name}
                    </Link>
                  </TableCell>
                  <TableCell>{r.version_label}</TableCell>
                  <TableCell>{r.suite_name ?? "—"}</TableCell>
                  <TableCell>
                    <GateBadge passed={r.gate_passed} status={r.status} />
                  </TableCell>
                  <TableCell className={cn("font-mono", arsColor(r.ars))}>{formatAr(r.ars)}</TableCell>
                  <TableCell>{r.triggered_by}</TableCell>
                  <TableCell className="whitespace-nowrap text-muted-foreground" title={formatDateTime(r.created_at)}>
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
