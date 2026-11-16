import { useParams } from "react-router-dom";
import { RoleGate } from "@/components/RoleGate";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useCandidateCases, useReviewCandidate } from "@/hooks/useCandidateCases";
import { useRunMining } from "@/hooks/useFailureClusters";

export function FailureClustersPage() {
  const { agentId } = useParams<{ agentId: string }>();
  const runMining = useRunMining(agentId ?? "");
  const { data: pending, isLoading } = useCandidateCases(agentId, "pending");
  const reviewCandidate = useReviewCandidate(agentId);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Failure Clusters</h1>
        <RoleGate allow={["admin", "developer"]}>
          <Button onClick={() => runMining.mutate()} disabled={runMining.isPending}>
            {runMining.isPending ? "Mining…" : "Run Mining"}
          </Button>
        </RoleGate>
      </div>

      {runMining.isError && (
        <p className="text-sm text-destructive">{runMining.error.message}</p>
      )}

      {runMining.isSuccess && (
        <section>
          <h2 className="mb-2 text-sm font-medium text-muted-foreground">
            Clusters found ({runMining.data.length})
          </h2>
          <div className="grid gap-3 md:grid-cols-2">
            {runMining.data.map((cluster) => (
              <Card key={cluster.id}>
                <CardHeader>
                  <CardTitle className="flex items-center justify-between text-sm">
                    <span>Cluster {cluster.cluster_label}</span>
                    <Badge variant="secondary">{cluster.size} members</Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="mb-2 text-xs text-muted-foreground">
                    {(cluster.bad_outcome_rate * 100).toFixed(0)}% bad outcome rate
                  </div>
                  <p className="line-clamp-3 text-sm">{cluster.representative_text}</p>
                </CardContent>
              </Card>
            ))}
          </div>
          {runMining.data.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No significant failure clusters found in this agent's eval history.
            </p>
          )}
        </section>
      )}

      <section>
        <h2 className="mb-2 text-sm font-medium text-muted-foreground">
          Pending candidate cases
        </h2>
        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        <div className="space-y-3">
          {pending?.map((candidate) => (
            <Card key={candidate.id}>
              <CardContent className="flex items-center justify-between py-4">
                <div>
                  <div className="font-medium">{candidate.case_key}</div>
                  <div className="text-xs text-muted-foreground">
                    Created {new Date(candidate.created_at).toLocaleString()}
                  </div>
                </div>
                <RoleGate allow={["admin", "developer"]}>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={reviewCandidate.isPending}
                      onClick={() =>
                        reviewCandidate.mutate({ candidateId: candidate.id, action: "reject" })
                      }
                    >
                      Reject
                    </Button>
                    <Button
                      size="sm"
                      disabled={reviewCandidate.isPending}
                      onClick={() =>
                        reviewCandidate.mutate({ candidateId: candidate.id, action: "approve" })
                      }
                    >
                      Approve
                    </Button>
                  </div>
                </RoleGate>
              </CardContent>
            </Card>
          ))}
        </div>
        {pending?.length === 0 && !isLoading && (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No candidates pending review.
          </p>
        )}
      </section>
    </div>
  );
}
