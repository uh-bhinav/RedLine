import { Check, DatabaseZap, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { EmptyState } from "@/components/EmptyState";
import { ErrorCard } from "@/components/ErrorCard";
import { RoleGate } from "@/components/RoleGate";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useCandidateCases, useReviewCandidate } from "@/hooks/useCandidateCases";
import { useClusters, useDismissedClusters, useRunMining } from "@/hooks/useFailureClusters";
import { errorMessage } from "@/lib/queryClient";
import { timeAgo } from "@/lib/utils";

function MiningButton({
  agentId,
  label,
  variant = "default",
}: {
  agentId: string;
  label: string;
  variant?: "default" | "outline";
}) {
  const mining = useRunMining(agentId);
  return (
    <RoleGate allow={["admin", "developer"]}>
      <Button
        variant={variant}
        disabled={mining.isPending}
        onClick={() =>
          mining.mutate(undefined, {
            onSuccess: (c) =>
              toast.success(
                c.length === 0
                  ? "Mining finished: no significant failure clusters found"
                  : `Mining finished: ${c.length} cluster${c.length === 1 ? "" : "s"} found`,
              ),
            onError: (e) => toast.error(`Mining failed: ${errorMessage(e)}`),
          })
        }
      >
        {mining.isPending && <Loader2 className="animate-spin" />}
        {mining.isPending ? "Mining..." : label}
      </Button>
    </RoleGate>
  );
}

/** Failure clusters + pending candidate-case review, inline in the agent detail page. */
export function FailureClustersTab({ agentId }: { agentId: string }) {
  const clusters = useClusters(agentId);
  const pending = useCandidateCases(agentId, "pending");
  const review = useReviewCandidate(agentId);
  const { visible, dismiss, restoreAll, dismissedIds } = useDismissedClusters(agentId);

  if (clusters.isLoading) return <Skeleton className="h-40 w-full" />;
  if (clusters.error) {
    return <ErrorCard error={clusters.error} onRetry={() => void clusters.refetch()} />;
  }

  const shown = visible(clusters.data ?? []);
  const hasAny = (clusters.data ?? []).length > 0;

  return (
    <div className="space-y-6">
      {!hasAny ? (
        <Card>
          <EmptyState
            icon={DatabaseZap}
            title="No failure clusters yet"
            description="Run the mining analysis to auto-discover recurring failure patterns"
            action={<MiningButton agentId={agentId} label="Run Mining Analysis" />}
          />
        </Card>
      ) : (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-medium text-muted-foreground">
              Failure clusters ({shown.length})
            </h2>
            <div className="flex items-center gap-2">
              {dismissedIds.length > 0 && (
                <Button variant="ghost" size="sm" onClick={restoreAll}>
                  Restore {dismissedIds.length} dismissed
                </Button>
              )}
              <MiningButton agentId={agentId} label="Re-run Mining" variant="outline" />
            </div>
          </div>
          {shown.length === 0 && (
            <p className="py-4 text-center text-sm text-muted-foreground">
              All clusters dismissed.
            </p>
          )}
          {shown.map((c) => (
            <Card key={c.id} className="p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold">Cluster {c.cluster_label}</span>
                <span className="text-muted-foreground">&middot;</span>
                <span className="text-sm">
                  {c.size} case{c.size === 1 ? "" : "s"}
                </span>
                <span className="text-muted-foreground">&middot;</span>
                <Badge variant="fail">{Math.round(c.bad_outcome_rate * 100)}% bad outcome</Badge>
              </div>
              <p className="mt-2 text-sm">&ldquo;{c.representative_text}&rdquo;</p>
              <div className="mt-3 flex flex-wrap justify-end gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => toast.success("Case promoted - add it to your eval suite YAML")}
                >
                  Promote to Test Suite
                </Button>
                <Button size="sm" variant="ghost" onClick={() => dismiss(c.id)}>
                  Dismiss
                </Button>
              </div>
            </Card>
          ))}
        </section>
      )}

      <section className="space-y-3">
        <h2 className="text-sm font-medium text-muted-foreground">
          Pending Review{pending.data ? ` (${pending.data.length})` : ""}
        </h2>
        {pending.isLoading && <Skeleton className="h-16 w-full" />}
        {pending.error && (
          <ErrorCard error={pending.error} onRetry={() => void pending.refetch()} />
        )}
        {pending.data?.length === 0 && (
          <p className="py-4 text-center text-sm text-muted-foreground">
            No candidates pending review.
          </p>
        )}
        {pending.data?.map((cand) => (
          <Card key={cand.id} className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div className="min-w-0">
              <div className="truncate font-medium">{cand.case_key}</div>
              <div className="text-xs text-muted-foreground">
                Created {timeAgo(cand.created_at)}
              </div>
            </div>
            <RoleGate allow={["admin", "developer"]}>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  disabled={review.isPending}
                  onClick={() =>
                    review.mutate(
                      { candidateId: cand.id, action: "approve" },
                      {
                        onSuccess: () => toast.success(`Approved ${cand.case_key}`),
                        onError: (e) => toast.error(`Approve failed: ${errorMessage(e)}`),
                      },
                    )
                  }
                >
                  <Check />
                  Approve
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={review.isPending}
                  onClick={() =>
                    review.mutate(
                      { candidateId: cand.id, action: "reject" },
                      {
                        onSuccess: () => toast.success(`Rejected ${cand.case_key}`),
                        onError: (e) => toast.error(`Reject failed: ${errorMessage(e)}`),
                      },
                    )
                  }
                >
                  <X />
                  Reject
                </Button>
              </div>
            </RoleGate>
          </Card>
        ))}
      </section>
    </div>
  );
}
