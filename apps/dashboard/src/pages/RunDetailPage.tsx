import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { GateResultBanner } from "@/components/GateResultBanner";
import { TranscriptViewer } from "@/components/TranscriptViewer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useRunDetail } from "@/hooks/useRunDetail";
import type { TranscriptTurn } from "@/lib/types";

export function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const { data: run, isLoading, error } = useRunDetail(runId);
  const [expandedCase, setExpandedCase] = useState<string | null>(null);
  const [chaosOnly, setChaosOnly] = useState(false);

  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (error || !run) {
    return (
      <p className="text-sm text-destructive">
        Failed to load run: {error?.message ?? "not found"}
      </p>
    );
  }

  const hasChaosCases = run.case_results.some((c) => c.is_chaos_case);
  const visibleCases = chaosOnly
    ? run.case_results.filter((c) => c.is_chaos_case)
    : run.case_results;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="font-mono text-lg font-semibold">{run.id}</h1>
        <Link to={`/runs/${run.id}/traces`} className="text-sm text-primary hover:underline">
          View traces →
        </Link>
      </div>

      <GateResultBanner gateResult={run.gate_result} status={run.status} />

      <div className="grid grid-cols-3 gap-4 text-sm">
        <div>
          <div className="text-muted-foreground">Triggered by</div>
          <div>{run.triggered_by}</div>
        </div>
        <div>
          <div className="text-muted-foreground">Started</div>
          <div>{run.started_at ? new Date(run.started_at).toLocaleString() : "—"}</div>
        </div>
        <div>
          <div className="text-muted-foreground">Completed</div>
          <div>{run.completed_at ? new Date(run.completed_at).toLocaleString() : "—"}</div>
        </div>
      </div>

      {run.error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm">
          {run.error}
        </div>
      )}

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-medium text-muted-foreground">Per-case results</h2>
          {hasChaosCases && (
            <Button variant="outline" size="sm" onClick={() => setChaosOnly((v) => !v)}>
              {chaosOnly ? "Show all cases" : "Chaos-faulted only"}
            </Button>
          )}
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8" />
              <TableHead>Case</TableHead>
              <TableHead>Result</TableHead>
              <TableHead>Latency</TableHead>
              <TableHead>Cost</TableHead>
              <TableHead>Chaos</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {visibleCases.map((c) => (
              <>
                <TableRow
                  key={c.case_id}
                  className="cursor-pointer"
                  onClick={() =>
                    setExpandedCase(expandedCase === c.case_id ? null : c.case_id)
                  }
                >
                  <TableCell>
                    {expandedCase === c.case_id ? (
                      <ChevronDown className="h-4 w-4" />
                    ) : (
                      <ChevronRight className="h-4 w-4" />
                    )}
                  </TableCell>
                  <TableCell className="font-medium">{c.case_key}</TableCell>
                  <TableCell>
                    <Badge variant={c.passed ? "outline" : "destructive"}>
                      {c.passed ? "PASS" : "FAIL"}
                    </Badge>
                  </TableCell>
                  <TableCell>{c.latency_ms}ms</TableCell>
                  <TableCell>${c.cost_usd.toFixed(6)}</TableCell>
                  <TableCell>
                    {c.is_chaos_case && <Badge variant="secondary">chaos</Badge>}
                  </TableCell>
                </TableRow>
                {expandedCase === c.case_id && (
                  <TableRow key={`${c.case_id}-detail`}>
                    <TableCell colSpan={6} className="bg-muted/30">
                      <div className="space-y-4 py-2">
                        <TranscriptViewer transcript={c.transcript as unknown as TranscriptTurn[]} />
                        <div>
                          <h3 className="mb-1 text-xs font-medium text-muted-foreground">
                            Scorer results
                          </h3>
                          <div className="space-y-1 font-mono text-xs">
                            {Object.entries(c.scorer_results as Record<string, { passed: boolean; detail: string }>).map(
                              ([scorer, result]) => (
                                <div key={scorer}>
                                  {result.passed ? "✓" : "✗"} {scorer}: {result.detail}
                                </div>
                              ),
                            )}
                          </div>
                        </div>
                      </div>
                    </TableCell>
                  </TableRow>
                )}
              </>
            ))}
          </TableBody>
        </Table>
      </section>
    </div>
  );
}
