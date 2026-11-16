import { Wrench } from "lucide-react";
import { cn, formatCost } from "@/lib/utils";
import type { TranscriptTurn } from "@/lib/types";

/**
 * Chat-bubble transcript: user turns left, assistant turns right, tool calls
 * as dashed chips above the assistant bubble. Chaos awareness stays at case
 * level (`is_chaos_case`); no per-turn marker parsing here.
 */
export function TranscriptViewer({ transcript }: { transcript: TranscriptTurn[] }) {
  if (transcript.length === 0) {
    return <p className="text-sm text-muted-foreground">No transcript recorded.</p>;
  }

  return (
    <div className="space-y-3 py-1">
      {transcript.map((turn, i) => (
        <div key={i} className="space-y-2">
          {turn.role === "assistant" &&
            turn.tool_calls?.map((tc, j) => (
              <div
                key={j}
                className="mx-auto max-w-[90%] rounded-md border border-dashed bg-muted/40 px-3 py-1.5 font-mono text-xs text-muted-foreground"
              >
                <Wrench className="mr-1.5 inline size-3" />
                {tc.name}
                {tc.arguments && Object.keys(tc.arguments).length > 0
                  ? ` ${JSON.stringify(tc.arguments)}`
                  : ""}
                {tc.result !== undefined && (
                  <span className="ml-2 opacity-70">→ {JSON.stringify(tc.result)}</span>
                )}
              </div>
            ))}
          <div className={cn("flex", turn.role === "user" ? "justify-start" : "justify-end")}>
            <div
              className={cn(
                "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm",
                turn.role === "user"
                  ? "rounded-bl-sm border bg-background"
                  : "rounded-br-sm bg-muted",
              )}
            >
              <div className="mb-0.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                {turn.role}
              </div>
              <p className="whitespace-pre-wrap">{turn.content}</p>
              {turn.role === "assistant" &&
                (turn.latency_ms != null || turn.cost_usd != null) && (
                  <div className="mt-1.5 font-mono text-[11px] text-muted-foreground">
                    {turn.latency_ms != null && `Latency: ${turn.latency_ms}ms`}
                    {turn.latency_ms != null && turn.cost_usd != null && " · "}
                    {turn.cost_usd != null && `Cost: ${formatCost(turn.cost_usd)}`}
                  </div>
                )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
