import { Link, useParams } from "react-router-dom";
import { ArsTrendChart } from "@/components/ArsTrendChart";
import { DriftAlertsList } from "@/components/DriftAlertsList";
import { ErrorBudgetGauge } from "@/components/ErrorBudgetGauge";
import { GateResultBanner } from "@/components/GateResultBanner";
import { RoleGate } from "@/components/RoleGate";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TriggerDiffRunDialog } from "@/components/TriggerDiffRunDialog";
import { TriggerEvalRunDialog } from "@/components/TriggerEvalRunDialog";
import { TriggerLoadRunDialog } from "@/components/TriggerLoadRunDialog";
import { useAgentDetail } from "@/hooks/useAgentDetail";
import { useArsHistory } from "@/hooks/useArsHistory";
import { useCandidateCases } from "@/hooks/useCandidateCases";
import { useDriftAlerts } from "@/hooks/useDriftAlerts";
import { useErrorBudget } from "@/hooks/useErrorBudget";
import { useLoadRuns } from "@/hooks/useLoadRuns";

export function AgentDetailPage() {
  const { agentId } = useParams<{ agentId: string }>();
  const { data: agent, isLoading, error } = useAgentDetail(agentId);
  const { data: arsHistory } = useArsHistory(agentId);
  const { data: errorBudget } = useErrorBudget(agentId);
  const { data: driftAlerts } = useDriftAlerts(agentId);
  const { data: loadRuns } = useLoadRuns(agentId);
  const { data: pendingCandidates } = useCandidateCases(agentId, "pending");

  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (error || !agent) {
    return (
      <p className="text-sm text-destructive">
        Failed to load agent: {error?.message ?? "not found"}
      </p>
    );
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">{agent.name}</h1>
          {agent.description && (
            <p className="text-sm text-muted-foreground">{agent.description}</p>
          )}
        </div>
        <RoleGate allow={["admin", "developer"]}>
          <div className="flex gap-2">
            <TriggerDiffRunDialog agentId={agent.id} versions={agent.versions} />
            <TriggerLoadRunDialog agentId={agent.id} versions={agent.versions} />
            <TriggerEvalRunDialog agentId={agent.id} versions={agent.versions} />
          </div>
        </RoleGate>
      </div>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="ars-trend">ARS Trend</TabsTrigger>
          <TabsTrigger value="drift-alerts">Drift Alerts</TabsTrigger>
          <TabsTrigger value="load-tests">Load Tests</TabsTrigger>
          <TabsTrigger value="clusters">Failure Clusters</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          <section>
            <h2 className="mb-2 text-sm font-medium text-muted-foreground">Versions</h2>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Label</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead>Content hash</TableHead>
                  <TableHead>Registered</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {agent.versions.map((v) => (
                  <TableRow key={v.id}>
                    <TableCell className="font-medium">{v.version_label}</TableCell>
                    <TableCell>{v.model_name}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {v.content_hash.slice(0, 12)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(v.created_at).toLocaleDateString()}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </section>

          <section>
            <h2 className="mb-2 text-sm font-medium text-muted-foreground">Recent runs</h2>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Run</TableHead>
                  <TableHead>Gate</TableHead>
                  <TableHead>Triggered by</TableHead>
                  <TableHead>Completed</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {agent.recent_runs.map((run) => (
                  <TableRow key={run.id}>
                    <TableCell>
                      <Link to={`/runs/${run.id}`} className="font-mono text-xs hover:underline">
                        {run.id.slice(0, 8)}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <GateResultBanner
                        variant="badge"
                        status={run.status}
                        gateResult={run.gate_result}
                      />
                    </TableCell>
                    <TableCell>{run.triggered_by}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {run.completed_at ? new Date(run.completed_at).toLocaleString() : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {agent.recent_runs.length === 0 && (
              <p className="py-6 text-center text-sm text-muted-foreground">No runs yet.</p>
            )}
          </section>
        </TabsContent>

        <TabsContent value="ars-trend" className="space-y-4">
          {errorBudget && <ErrorBudgetGauge budget={errorBudget} />}
          <ArsTrendChart snapshots={arsHistory ?? []} />
        </TabsContent>

        <TabsContent value="drift-alerts">
          <DriftAlertsList alerts={driftAlerts ?? []} />
        </TabsContent>

        <TabsContent value="load-tests">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Run</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Concurrency</TableHead>
                <TableHead>p95</TableHead>
                <TableHead>Error rate</TableHead>
                <TableHead>Cost/hour</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loadRuns?.map((run) => (
                <TableRow key={run.id}>
                  <TableCell>
                    <Link to={`/load-run/${run.id}`} className="font-mono text-xs hover:underline">
                      {run.id.slice(0, 8)}
                    </Link>
                  </TableCell>
                  <TableCell>{run.status}</TableCell>
                  <TableCell>{run.concurrency}</TableCell>
                  <TableCell>{run.p95_latency_ms != null ? `${run.p95_latency_ms}ms` : "—"}</TableCell>
                  <TableCell>
                    {run.error_rate != null ? `${(run.error_rate * 100).toFixed(1)}%` : "—"}
                  </TableCell>
                  <TableCell>
                    {run.cost_per_hour_usd != null ? `$${run.cost_per_hour_usd.toFixed(2)}` : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {loadRuns?.length === 0 && (
            <p className="py-6 text-center text-sm text-muted-foreground">No load tests yet.</p>
          )}
        </TabsContent>

        <TabsContent value="clusters" className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              {pendingCandidates?.length ?? 0} candidate case(s) awaiting review.
            </p>
            <Link to={`/agent/${agent.id}/clusters`}>
              <Button variant="outline">Review clusters →</Button>
            </Link>
          </div>
          {pendingCandidates && pendingCandidates.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {pendingCandidates.slice(0, 5).map((c) => (
                <Badge key={c.id} variant="secondary">
                  {c.case_key}
                </Badge>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
