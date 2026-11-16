import { CheckCircle2, ChevronDown, XCircle, Zap } from "lucide-react";
import { useState } from "react";
import { TranscriptViewer } from "@/components/TranscriptViewer";
import { Badge } from "@/components/ui/badge";
import type { CaseResultItem, TranscriptTurn } from "@/lib/types";
import { cn, formatCost } from "@/lib/utils";

interface ScorerEntry {
  passed: boolean;
  detail?: string;
  reasoning?: string;
}

/** Scorer results as styled rows: check/x icon, scorer name, reasoning text. */
export function ScorerRows({ results }: { results: Record<string, unknown> }) {
  const entries = Object.entries(results) as [string, ScorerEntry][];
  if (entries.length === 0) {
    return <p className="text-sm text-muted-foreground">No scorer results recorded.</p>;
  }
  return (
    <ul className="space-y-2">
      {entries.map(([name, r]) => (
        <li
          key={name}
          className={cn(
            "flex gap-3 rounded-md border p-3 text-sm",
            r.passed ? "border-green-500/30 bg-green-500/5" : "border-red-500/30 bg-red-500/5",
          )}
        >
          {r.passed ? (
            <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-green-600 dark:text-green-400" />
          ) : (
            <XCircle className="mt-0.5 size-4 shrink-0 text-red-600 dark:text-red-400" />
          )}
          <div className="min-w-0">
            <div className="font-medium">{name}</div>
            <p className="whitespace-pre-wrap break-words text-muted-foreground">
              {r.reasoning ?? r.detail ?? (r.passed ? "Passed" : "Failed")}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}

const FAIL_RE = /^\s*"?(failed|error)|\bFAILED\b/i;

/**
 * Multi-agent chain (e.g. planner -> retriever -> writer -> verifier) derived from
 * the transcript's tool calls; a step whose result reports FAILED/error is flagged.
 */
function AgentChain({ transcript }: { transcript: TranscriptTurn[] }) {
  const steps = transcript.flatMap((t) => t.tool_calls ?? []);
  if (steps.length < 2) return null;
  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Agent chain
      </h3>
      <ol className="flex flex-wrap items-center gap-2">
        {steps.map((s, i) => {
          const text = typeof s.result === "string" ? s.result : JSON.stringify(s.result ?? "");
          const failed = FAIL_RE.test(text);
          return (
            <li key={i} className="flex items-center gap-2">
              {i > 0 && <span className="text-muted-foreground">&rarr;</span>}
              <span
                title={text}
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 font-mono text-xs",
                  failed
                    ? "border-red-500/50 bg-red-500/10 font-semibold text-red-700 dark:text-red-400"
                    : "border-green-500/30 bg-green-500/5",
                )}
              >
                {failed ? <XCircle className="size-3" /> : <CheckCircle2 className="size-3" />}
                {s.name}
                {failed && " FAILED"}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/** One per-case panel that expands inline (no table, no chevron-row pattern). */
export function CaseResultRow({
  result,
  defaultOpen = false,
}: {
  result: CaseResultItem;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const transcript = result.transcript as unknown as TranscriptTurn[];
  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border bg-card",
        !result.passed && "border-l-4 border-l-red-500",
      )}
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-left hover:bg-muted/40"
      >
        {result.passed ? (
          <CheckCircle2 className="size-4 shrink-0 text-green-600 dark:text-green-400" />
        ) : (
          <XCircle className="size-4 shrink-0 text-red-600 dark:text-red-400" />
        )}
        <span className="min-w-0 flex-1 truncate font-medium">{result.case_key}</span>
        <Badge variant={result.passed ? "pass" : "fail"}>{result.passed ? "PASS" : "FAIL"}</Badge>
        {result.is_chaos_case && (
          <Badge variant="warn">
            <Zap className="size-3" />
            Chaos-injected
          </Badge>
        )}
        <span className="font-mono text-xs text-muted-foreground">
          {result.latency_ms}ms &middot; {formatCost(result.cost_usd)}
        </span>
        <ChevronDown
          className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <div className="space-y-4 border-t bg-muted/20 p-4">
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Scorer results
            </h3>
            <ScorerRows results={result.scorer_results} />
          </section>
          <AgentChain transcript={transcript} />
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Transcript
            </h3>
            <TranscriptViewer transcript={transcript} />
          </section>
        </div>
      )}
    </div>
  );
}
