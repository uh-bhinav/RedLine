import { useParams } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useDiffRun } from "@/hooks/useDiffRun";
import { useRunDetail } from "@/hooks/useRunDetail";
import type { RunDetailResponse, TranscriptTurn } from "@/lib/types";

const CLASSIFICATION_STYLES: Record<string, string> = {
  no_op: "bg-muted text-muted-foreground",
  safe_refactor: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  expected_change: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  silent_drift: "bg-destructive text-destructive-foreground",
  insufficient_data: "bg-muted text-muted-foreground",
};

function finalAssistantMessage(run: RunDetailResponse | undefined, caseKey: string): string {
  const caseResult = run?.case_results.find((c) => c.case_key === caseKey);
  if (!caseResult) return "(case not found in this run)";
  const transcript = caseResult.transcript as unknown as TranscriptTurn[];
  const assistantTurns = transcript.filter((t) => t.role === "assistant");
  return assistantTurns.at(-1)?.content ?? "(no assistant response)";
}

export function DiffViewerPage() {
  const { diffId } = useParams<{ diffId: string }>();
  const { data: diff, isLoading, error } = useDiffRun(diffId);
  const { data: runA } = useRunDetail(diff?.eval_run_a_id);
  const { data: runB } = useRunDetail(diff?.eval_run_b_id);

  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (error || !diff) {
    return (
      <p className="text-sm text-destructive">
        Failed to load diff: {error?.message ?? "not found"}
      </p>
    );
  }

  const caseKeys = Object.keys(diff.per_case_similarity).sort();

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Badge className={CLASSIFICATION_STYLES[diff.classification] ?? ""}>
          {diff.classification.replace("_", " ").toUpperCase()}
        </Badge>
        <span className="text-sm text-muted-foreground">
          mean similarity {diff.mean_similarity.toFixed(3)} (threshold {diff.threshold.toFixed(2)})
        </span>
      </div>

      {diff.classification === "silent_drift" && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm">
          Code did not change, but behavior did -- likely a silent model/provider update.
        </div>
      )}

      <p className="text-sm text-muted-foreground">{diff.detail}</p>

      <div className="space-y-6">
        {caseKeys.map((caseKey) => {
          const similarity = diff.per_case_similarity[caseKey];
          return (
            <div key={caseKey} className="rounded-lg border">
              <div className="flex items-center justify-between border-b bg-muted/30 px-4 py-2">
                <span className="font-medium">{caseKey}</span>
                <span
                  className={
                    similarity < diff.threshold
                      ? "text-sm font-medium text-destructive"
                      : "text-sm text-muted-foreground"
                  }
                >
                  similarity {similarity.toFixed(3)}
                </span>
              </div>
              <div className="grid grid-cols-2 divide-x">
                <div className="p-4 text-sm">
                  <div className="mb-2 text-xs font-medium text-muted-foreground">Version A</div>
                  <p className="whitespace-pre-wrap">{finalAssistantMessage(runA, caseKey)}</p>
                </div>
                <div className="p-4 text-sm">
                  <div className="mb-2 text-xs font-medium text-muted-foreground">Version B</div>
                  <p className="whitespace-pre-wrap">{finalAssistantMessage(runB, caseKey)}</p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      {caseKeys.length === 0 && (
        <p className="py-8 text-center text-sm text-muted-foreground">
          No shared case keys between these two runs.
        </p>
      )}
    </div>
  );
}
