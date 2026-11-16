import { cn } from "@/lib/utils";
import type { TranscriptTurn } from "@/lib/types";

/**
 * Turn-by-turn chat rendering. Deliberately case-level chaos awareness only
 * (no per-turn marker parsing here) -- has_chaos_marker()'s exact tool-call
 * shape is a backend implementation detail; the frontend trusts the
 * `is_chaos_case` boolean the API already computed rather than re-deriving it.
 */
export function TranscriptViewer({ transcript }: { transcript: TranscriptTurn[] }) {
  if (transcript.length === 0) {
    return <p className="text-sm text-muted-foreground">No transcript recorded.</p>;
  }

  return (
    <div className="space-y-3">
      {transcript.map((turn, i) => (
        <div
          key={i}
          className={cn(
            "flex flex-col rounded-lg border p-3 text-sm",
            turn.role === "assistant" ? "ml-6 bg-muted/50" : "mr-6 bg-background",
          )}
        >
          <div className="mb-1 flex items-center justify-between text-xs font-medium text-muted-foreground">
            <span className="uppercase">{turn.role}</span>
            {(turn.latency_ms != null || turn.cost_usd != null) && (
              <span className="font-normal">
                {turn.latency_ms != null && `${turn.latency_ms}ms`}
                {turn.latency_ms != null && turn.cost_usd != null && " · "}
                {turn.cost_usd != null && `$${turn.cost_usd.toFixed(6)}`}
              </span>
            )}
          </div>
          <p className="whitespace-pre-wrap">{turn.content}</p>
          {turn.tool_calls && turn.tool_calls.length > 0 && (
            <div className="mt-2 space-y-1 border-t pt-2">
              {turn.tool_calls.map((tc, j) => (
                <div key={j} className="font-mono text-xs text-muted-foreground">
                  🔧 {tc.name}
                  {tc.arguments && Object.keys(tc.arguments).length > 0
                    ? ` ${JSON.stringify(tc.arguments)}`
                    : ""}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
