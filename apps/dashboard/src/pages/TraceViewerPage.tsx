import { Activity } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { EmptyState } from "@/components/EmptyState";
import { ErrorCard } from "@/components/ErrorCard";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useTraces } from "@/hooks/useTraces";
import type { TraceEventItem } from "@/lib/types";
import { cn, formatCost, shortId } from "@/lib/utils";

// Small-N, sequence-shaped event data (run_started -> turn_completed x N ->
// run_completed per case) reads better as an ordered timeline than as a
// scatter/bar chart forcing an axis mapping that doesn't naturally fit.
function groupByCaseKey(events: TraceEventItem[]): Map<string, TraceEventItem[]> {
  const groups = new Map<string, TraceEventItem[]>();
  for (const event of events) {
    const key = event.case_key || "(run-level)";
    const list = groups.get(key) ?? [];
    list.push(event);
    groups.set(key, list);
  }
  return groups;
}

function EventRow({ event, maxLatencyMs }: { event: TraceEventItem; maxLatencyMs: number }) {
  const failed = event.passed === false;
  const barWidthPct = maxLatencyMs > 0 ? Math.max(2, (event.latency_ms / maxLatencyMs) * 100) : 0;

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-1 border-b py-2 text-sm last:border-b-0",
        failed && "text-destructive",
      )}
    >
      <span className="w-10 shrink-0 text-xs text-muted-foreground">
        {event.turn_index >= 0 ? `#${event.turn_index}` : ""}
      </span>
      <span className="w-36 shrink-0 font-mono text-xs">{event.event_type}</span>
      <div className="order-last w-full sm:order-none sm:w-auto sm:flex-1">
        <div className="h-2 w-full overflow-hidden rounded bg-muted">
          <div
            className={cn("h-full rounded", failed ? "bg-destructive" : "bg-primary")}
            style={{ width: `${barWidthPct}%` }}
          />
        </div>
      </div>
      <span className="w-16 shrink-0 text-right text-xs tabular-nums">{event.latency_ms}ms</span>
      <span className="w-20 shrink-0 text-right text-xs tabular-nums">{formatCost(event.cost_usd)}</span>
      {event.passed !== null && (
        <Badge variant={event.passed ? "pass" : "fail"} className="shrink-0">
          {event.passed ? "PASS" : "FAIL"}
        </Badge>
      )}
      {failed && <span className="shrink-0 text-xs font-semibold">&lt;- FAILED</span>}
    </div>
  );
}

export function TraceViewerPage() {
  const { runId } = useParams<{ runId: string }>();
  const id8 = runId ? shortId(runId) : "";
  useDocumentTitle(`Traces - Run ${id8}`);
  const { data: traces, isLoading, error, refetch } = useTraces(runId);

  const header = (
    <div>
      <h1 className="text-xl font-semibold">Trace Timeline</h1>
      <p className="text-sm text-muted-foreground">
        Run{" "}
        {runId ? (
          <Link to={`/runs/${runId}`} className="font-mono hover:underline">
            {id8}
          </Link>
        ) : null}
      </p>
    </div>
  );

  if (isLoading) {
    return (
      <div className="space-y-3">
        {header}
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        {header}
        <ErrorCard error={error} onRetry={() => void refetch()} />
      </div>
    );
  }

  if (!traces || traces.length === 0) {
    return (
      <div className="space-y-4">
        {header}
        <EmptyState
          icon={Activity}
          title="No trace events recorded"
          description="Traces are written to ClickHouse while a run executes. This run has none."
        />
      </div>
    );
  }

  const grouped = groupByCaseKey(traces);
  const maxLatencyMs = Math.max(...traces.map((e) => e.latency_ms), 1);

  return (
    <div className="space-y-6">
      {header}
      {Array.from(grouped.entries()).map(([caseKey, events]) => {
        const totalLatency = events.reduce((s, e) => s + e.latency_ms, 0);
        const totalCost = events.reduce((s, e) => s + e.cost_usd, 0);
        const failedCount = events.filter((e) => e.passed === false).length;
        return (
          <section key={caseKey} className="overflow-hidden rounded-lg border">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/30 px-4 py-2">
              <span className="font-medium">{caseKey}</span>
              <span className="text-xs tabular-nums text-muted-foreground">
                {events.length} events - total latency {totalLatency}ms - total cost {formatCost(totalCost)}
                {failedCount > 0 && (
                  <span className="ml-2 font-semibold text-destructive">{failedCount} failed</span>
                )}
              </span>
            </div>
            <div className="px-4">
              {events.map((event) => (
                <EventRow key={event.trace_id} event={event} maxLatencyMs={maxLatencyMs} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
