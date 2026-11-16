import { CheckCircle2, ExternalLink, Loader2, XCircle } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArsBreakdownBars } from "@/components/ArsBreakdownBars";
import { CaseResultRow } from "@/components/CaseResultRow";
import { ErrorCard } from "@/components/ErrorCard";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useRunDetail } from "@/hooks/useRunDetail";
import type { RunDetailResponse } from "@/lib/types";
import { cn, shortId, timeAgo } from "@/lib/utils";

function titleFor(run: RunDetailResponse | undefined): string {
  if (!run) return "Run";
  if (run.status === "pending" || run.status === "running") return "Run in progress";
  if (run.status === "failed") return "Run errored";
  if (run.gate_result) return run.gate_result.passed ? "Gate passed" : "Gate failed";
  return `Run ${shortId(run.id)}`;
}

function Meta({ run }: { run: RunDetailResponse }) {
  const parts = [
    `Run ${shortId(run.id)}`,
    run.agent_name && run.version_label
      ? `${run.agent_name} ${run.version_label}`
      : (run.agent_name ?? run.version_label),
    run.suite_name ? `${run.suite_name} suite` : null,
  ].filter(Boolean);
  const done = run.completed_at
    ? `Completed ${timeAgo(run.completed_at)}`
    : run.started_at
      ? `Started ${timeAgo(run.started_at)}`
      : run.created_at
        ? `Queued ${timeAgo(run.created_at)}`
        : null;
  return (
    <div className="mt-4 space-y-0.5 border-t pt-3 text-sm text-muted-foreground">
      <div>
        {parts.map((p, i) => (
          <span key={i}>
            {i > 0 && <span className="mx-1.5">&middot;</span>}
            {i === 0 ? <span className="font-mono">{p}</span> : p}
          </span>
        ))}
      </div>
      <div>
        Triggered by: {run.triggered_by}
        {done && (
          <>
            <span className="mx-1.5">&middot;</span>
            {done}
          </>
        )}
      </div>
    </div>
  );
}

function Hero({ run }: { run: RunDetailResponse }) {
  const active = run.status === "pending" || run.status === "running";
  const failed = run.status === "failed";
  const gate = run.gate_result;

  let tone = "border-muted";
  let icon = <Loader2 className="size-12 shrink-0 animate-spin text-amber-500" />;
  let heading = run.status === "running" ? "RUN IN PROGRESS" : "RUN QUEUED";
  let headingClass = "text-amber-600 dark:text-amber-400";
  let body: React.ReactNode = (
    <p className="text-sm text-muted-foreground">
      The eval worker is scoring cases. This page updates automatically.
    </p>
  );

  if (failed) {
    tone = "border-red-500/40 bg-red-500/5";
    icon = <XCircle className="size-12 shrink-0 text-red-600" />;
    heading = "RUN ERRORED";
    headingClass = "text-red-600";
    body = (
      <pre className="whitespace-pre-wrap break-words rounded-md border border-red-500/30 bg-background p-3 font-mono text-sm">
        {run.error ?? "The run failed without an error message."}
      </pre>
    );
  } else if (!active && gate) {
    const passed = gate.passed;
    tone = passed ? "border-green-500/40 bg-green-500/5" : "border-red-500/40 bg-red-500/5";
    icon = passed ? (
      <CheckCircle2 className="size-12 shrink-0 text-green-600" />
    ) : (
      <XCircle className="size-12 shrink-0 text-red-600" />
    );
    heading = passed ? "GATE PASSED" : "GATE FAILED";
    headingClass = passed ? "text-green-600" : "text-red-600";
    body =
      gate.reasons.length > 0 ? (
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {gate.reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">All gate checks passed.</p>
      );
  } else if (!active) {
    heading = "NO GATE RESULT";
    headingClass = "text-muted-foreground";
    icon = <XCircle className="size-12 shrink-0 text-muted-foreground" />;
    body = <p className="text-sm text-muted-foreground">This run finished without a gate verdict.</p>;
  }

  return (
    <Card className={cn("border-2 p-5 sm:p-6", tone)}>
      <div className="flex items-center gap-4">
        {icon}
        <h1 className={cn("text-3xl font-bold tracking-tight sm:text-4xl", headingClass)}>
          {heading}
        </h1>
      </div>
      <div className="mt-4">{body}</div>
      {failed && run.gate_result && run.gate_result.reasons.length > 0 && (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm">
          {run.gate_result.reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
      <Meta run={run} />
    </Card>
  );
}

export function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const { data: run, isLoading, error, refetch } = useRunDetail(runId);
  const [chaosOnly, setChaosOnly] = useState(false);

  useDocumentTitle(titleFor(run));

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-44 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (error || !run) {
    return <ErrorCard error={error ?? new Error("Run not found")} onRetry={() => void refetch()} />;
  }

  const hasChaos = run.case_results.some((c) => c.is_chaos_case);
  const cases = chaosOnly ? run.case_results.filter((c) => c.is_chaos_case) : run.case_results;
  const passedCount = run.case_results.filter((c) => c.passed).length;

  return (
    <div className="space-y-5">
      <Hero run={run} />

      {run.ars && <ArsBreakdownBars ars={run.ars} />}

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-medium text-muted-foreground">
            Per-case results
            {run.case_results.length > 0 &&
              ` (${passedCount}/${run.case_results.length} passed)`}
          </h2>
          <div className="flex flex-wrap gap-2">
            {hasChaos && (
              <Button variant="outline" size="sm" onClick={() => setChaosOnly((v) => !v)}>
                {chaosOnly ? "Show all cases" : "Chaos-injected only"}
              </Button>
            )}
            <Button variant="outline" size="sm" asChild>
              <Link to={`/runs/${run.id}/traces`}>
                View Traces
                <ExternalLink />
              </Link>
            </Button>
          </div>
        </div>
        {cases.length === 0 && (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {run.status === "pending" || run.status === "running"
              ? "Case results will appear when the run completes."
              : "No case results recorded."}
          </p>
        )}
        {cases.map((c) => (
          <CaseResultRow key={c.case_id} result={c} />
        ))}
      </section>
    </div>
  );
}
