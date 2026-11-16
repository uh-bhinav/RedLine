import { GitCompare } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { EmptyState } from "@/components/EmptyState";
import { ErrorCard } from "@/components/ErrorCard";
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
import { useDiffs } from "@/hooks/useDiffs";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { timeAgo } from "@/lib/utils";

type Variant = "fail" | "info" | "pass" | "secondary";

const CLASS_BADGE: Record<string, { label: string; variant: Variant }> = {
  silent_drift: { label: "SILENT DRIFT", variant: "fail" },
  safe_refactor: { label: "SAFE REFACTOR", variant: "info" },
  expected_change: { label: "EXPECTED CHANGE", variant: "pass" },
  no_op: { label: "NO CHANGE", variant: "secondary" },
};

export function DiffsListPage() {
  useDocumentTitle("Diffs");
  const { data, isLoading, error, refetch } = useDiffs();
  const navigate = useNavigate();

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Behavioral Diffs</h1>
        <p className="text-sm text-muted-foreground">
          Version-to-version comparisons across all agents. Silent drift is flagged in red.
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
          icon={GitCompare}
          title="No diffs yet"
          description='Open an agent and use "Diff" to create the first behavioral diff.'
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Agent</TableHead>
                <TableHead>Versions</TableHead>
                <TableHead>Classification</TableHead>
                <TableHead className="text-right">Similarity</TableHead>
                <TableHead>When</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((d) => {
                const badge = CLASS_BADGE[d.classification] ?? {
                  label: d.classification.replace(/_/g, " ").toUpperCase(),
                  variant: "secondary" as Variant,
                };
                return (
                  <TableRow
                    key={d.id}
                    className="cursor-pointer"
                    onClick={() => navigate(`/diffs/${d.id}`)}
                  >
                    <TableCell className="font-medium">
                      <Link
                        to={`/diffs/${d.id}`}
                        className="hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {d.agent_name}
                      </Link>
                    </TableCell>
                    <TableCell className="whitespace-nowrap font-mono text-xs">
                      {d.version_a_label ?? "A"} vs {d.version_b_label ?? "B"}
                    </TableCell>
                    <TableCell>
                      <Badge variant={badge.variant}>{badge.label}</Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {d.mean_similarity.toFixed(3)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {timeAgo(d.created_at)}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
