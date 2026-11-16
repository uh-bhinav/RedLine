import { useParams } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useTraces } from "@/hooks/useTraces";
import type { TraceEventItem } from "@/lib/types";

// Small-N, sequence-shaped event data (run_started -> turn_completed x N ->
// run_completed per case) reads better as an ordered timeline than as a
// scatter/bar chart forcing an axis mapping that doesn't naturally fit --
// per the dataviz skill's form heuristic for this shape of data.
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
  const barWidthPct = maxLatencyMs > 0 ? Math.max(2, (event.latency_ms / maxLatencyMs) * 100) : 0;

  return (
    <div className="flex items-center gap-3 border-b py-2 text-sm last:border-b-0">
      <span className="w-10 shrink-0 text-xs text-muted-foreground">
        {event.turn_index >= 0 ? `#${event.turn_index}` : ""}
      </span>
      <span className="w-36 shrink-0 font-mono text-xs">{event.event_type}</span>
      <div className="flex-1">
        <div className="h-2 w-full overflow-hidden rounded bg-muted">
          <div
            className={cn(
              "h-full rounded",
              event.passed === false ? "bg-destructive" : "bg-primary",
            )}
            style={{ width: `${barWidthPct}%` }}
          />
        </div>
      </div>
      <span className="w-16 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
        {event.latency_ms}ms
      </span>
      <span className="w-20 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
        ${event.cost_usd.toFixed(6)}
      </span>
      {event.passed !== null && (
        <Badge variant={event.passed ? "outline" : "destructive"} className="shrink-0">
          {event.passed ? "PASS" : "FAIL"}
        </Badge>
      )}
    </div>
  );
}

export function TraceViewerPage() {
  const { runId } = useParams<{ runId: string }>();
  const { data: traces, isLoading, error } = useTraces(runId);

  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error) {
    return (
      <p className="text-sm text-destructive">Failed to load traces: {error.message}</p>
    );
  }

  if (!traces || traces.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        No trace events recorded for this run.
      </p>
    );
  }

  const grouped = groupByCaseKey(traces);
  const maxLatencyMs = Math.max(...traces.map((e) => e.latency_ms), 1);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Trace Timeline</h1>
      {Array.from(grouped.entries()).map(([caseKey, events]) => (
        <section key={caseKey} className="rounded-lg border">
          <div className="border-b bg-muted/30 px-4 py-2 font-medium">{caseKey}</div>
          <div className="px-4">
            {events.map((event) => (
              <EventRow key={event.trace_id} event={event} maxLatencyMs={maxLatencyMs} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
