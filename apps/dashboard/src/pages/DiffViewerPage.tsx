import { AlertOctagon, CheckCircle2, Equal, GitCompare, Loader2, Wrench } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { EmptyState } from "@/components/EmptyState";
import { ErrorCard } from "@/components/ErrorCard";
import { GateBadge } from "@/components/GateBadge";
import { SimilarityBar } from "@/components/SimilarityBar";
import { Skeleton } from "@/components/ui/skeleton";
import { useDiffRun } from "@/hooks/useDiffRun";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useRunDetail } from "@/hooks/useRunDetail";
import type { CaseResultItem, RunDetailResponse, TranscriptTurn } from "@/lib/types";
import { ACTIVE_STATUSES, cn } from "@/lib/utils";

interface ClassStyle {
  label: string;
  icon: LucideIcon;
  card: string;
  text: string;
  explanation: string;
}

const CLASSIFICATIONS: Record<string, ClassStyle> = {
  silent_drift: {
    label: "SILENT DRIFT DETECTED",
    icon: AlertOctagon,
    card: "border-red-500/60 bg-red-500/10",
    text: "text-red-600 dark:text-red-400",
    explanation:
      "The code content hash is identical between both versions. Behavior changed anyway - the model provider likely updated the underlying model without notice. This would be invisible to a code review.",
  },
  safe_refactor: {
    label: "SAFE REFACTOR",
    icon: Wrench,
    card: "border-blue-500/50 bg-blue-500/10",
    text: "text-blue-600 dark:text-blue-400",
    explanation: "The code changed but behavior stayed the same. The refactor did not alter outputs.",
  },
  expected_change: {
    label: "EXPECTED CHANGE",
    icon: CheckCircle2,
    card: "border-green-500/50 bg-green-500/10",
    text: "text-green-600 dark:text-green-400",
    explanation: "The code changed and behavior changed with it, as expected for an intentional update.",
  },
  no_op: {
    label: "NO CHANGE",
    icon: Equal,
    card: "border-border bg-muted/40",
    text: "text-muted-foreground",
    explanation: "Neither the code nor the behavior changed between these versions.",
  },
};

const FALLBACK: ClassStyle = {
  label: "UNCLASSIFIED",
  icon: GitCompare,
  card: "border-border bg-muted/40",
  text: "text-muted-foreground",
  explanation: "Not enough data to classify this comparison.",
};

function findCase(run: RunDetailResponse | undefined, caseKey: string): CaseResultItem | undefined {
  return run?.case_results.find((c) => c.case_key === caseKey);
}

function finalAssistantMessage(c: CaseResultItem | undefined, runLoaded: boolean): string {
  if (!runLoaded) return "Loading...";
  if (!c) return "(case not found in this run)";
  const transcript = c.transcript as unknown as TranscriptTurn[];
  return transcript.filter((t) => t.role === "assistant").at(-1)?.content ?? "(no assistant response)";
}

function OutputPane({
  title,
  result,
  runLoaded,
}: {
  title: string;
  result: CaseResultItem | undefined;
  runLoaded: boolean;
}) {
  return (
    <div className="min-w-0 p-4 text-sm">
      <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <span>{title}</span>
        {result && <GateBadge passed={result.passed} />}
      </div>
      <p className="whitespace-pre-wrap break-words">{finalAssistantMessage(result, runLoaded)}</p>
    </div>
  );
}

export function DiffViewerPage() {
  const { diffId } = useParams<{ diffId: string }>();
  const diffQuery = useDiffRun(diffId);
  const { data: diff } = diffQuery;
  const runAQuery = useRunDetail(diff?.eval_run_a_id);
  const runBQuery = useRunDetail(diff?.eval_run_b_id);
  const runA = runAQuery.data;
  const runB = runBQuery.data;

  useDocumentTitle(diff?.agent_name ? `Diff - ${diff.agent_name}` : "Diff");

  if (diffQuery.isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (diffQuery.error || !diff) {
    return <ErrorCard error={diffQuery.error ?? new Error("Diff not found")} onRetry={() => void diffQuery.refetch()} />;
  }

  const style = CLASSIFICATIONS[diff.classification] ?? FALLBACK;
  const Icon = style.icon;
  const caseKeys = Object.keys(diff.per_case_similarity).sort();
  const runsActive =
    (runA && ACTIVE_STATUSES.has(runA.status)) || (runB && ACTIVE_STATUSES.has(runB.status));
  const runsLoaded = !!runA && !!runB;
  const labelA = diff.version_a_label ?? "Version A";
  const labelB = diff.version_b_label ?? "Version B";

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Behavioral Diff</h1>
        <p className="text-sm text-muted-foreground">
          {diff.agent_id && diff.agent_name ? (
            <Link to={`/agent/${diff.agent_id}`} className="font-medium text-foreground hover:underline">
              {diff.agent_name}
            </Link>
          ) : (
            (diff.agent_name ?? "Agent")
          )}{" "}
          - {labelA} vs {labelB}
          {diff.suite_name ? ` - suite ${diff.suite_name}` : ""}
        </p>
      </div>

      <div className={cn("w-full rounded-xl border-2 p-5", style.card)} data-testid="classification-hero">
        <div className="flex items-center gap-3">
          <Icon className={cn("size-8 shrink-0", style.text)} />
          <div>
            <div className={cn("text-xl font-bold tracking-tight", style.text)}>{style.label}</div>
            <div className="text-sm text-muted-foreground">
              Mean similarity: {diff.mean_similarity.toFixed(2)} (threshold: {diff.threshold.toFixed(2)})
            </div>
          </div>
        </div>
        <p className="mt-3 text-sm">{style.explanation}</p>
        {diff.detail && <p className="mt-2 text-xs text-muted-foreground">{diff.detail}</p>}
      </div>

      {runsActive && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
          <Loader2 className="size-4 animate-spin" />
          Underlying eval runs are still in progress. Outputs will appear here automatically.
        </div>
      )}

      {(runAQuery.error || runBQuery.error) && (
        <ErrorCard
          error={runAQuery.error ?? runBQuery.error}
          onRetry={() => {
            void runAQuery.refetch();
            void runBQuery.refetch();
          }}
        />
      )}

      {caseKeys.length === 0 ? (
        <EmptyState icon={GitCompare} title="No shared cases between these runs" />
      ) : (
        <div className="space-y-4">
          {caseKeys.map((caseKey) => {
            const similarity = diff.per_case_similarity[caseKey];
            const below = similarity < diff.threshold;
            return (
              <div
                key={caseKey}
                className={cn("overflow-hidden rounded-lg border", below && "border-l-4 border-l-red-500")}
              >
                <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/30 px-4 py-2">
                  <span className="font-medium">{caseKey}</span>
                  <div className="w-64 max-w-full">
                    <SimilarityBar value={similarity} threshold={diff.threshold} />
                  </div>
                </div>
                <div className="grid grid-cols-1 divide-y md:grid-cols-2 md:divide-x md:divide-y-0">
                  <OutputPane title={`A - ${labelA}`} result={findCase(runA, caseKey)} runLoaded={runsLoaded} />
                  <OutputPane title={`B - ${labelB}`} result={findCase(runB, caseKey)} runLoaded={runsLoaded} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
