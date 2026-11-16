import { PlayCircle } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { AgentHealthHeader } from "@/components/AgentHealthHeader";
import { ArsTrendChart } from "@/components/ArsTrendChart";
import { DriftAlertsList } from "@/components/DriftAlertsList";
import { EmptyState } from "@/components/EmptyState";
import { ErrorCard } from "@/components/ErrorCard";
import { FailureClustersTab } from "@/components/FailureClustersTab";
import { GateBadge } from "@/components/GateBadge";
import { LoadTestsTab } from "@/components/LoadTestsTab";
import { RoleGate } from "@/components/RoleGate";
import { Card } from "@/components/ui/card";
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
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useDriftAlerts } from "@/hooks/useDriftAlerts";
import { useErrorBudget } from "@/hooks/useErrorBudget";
import { arsColor, cn, formatAr, formatDateTime, shortId, timeAgo } from "@/lib/utils";

const TABS = ["runs", "ars-trend", "drift-alerts", "clusters", "load-tests"] as const;
type TabValue = (typeof TABS)[number];

export function AgentDetailPage() {
  const { agentId } = useParams<{ agentId: string }>();
  const [params, setParams] = useSearchParams();
  const agent = useAgentDetail(agentId);
  const ars = useArsHistory(agentId);
  const budget = useErrorBudget(agentId);
  const drift = useDriftAlerts(agentId);

  useDocumentTitle(agent.data?.name ?? "Agent");

  const requested = params.get("tab");
  const tab: TabValue = (TABS as readonly string[]).includes(requested ?? "")
    ? (requested as TabValue)
    : "runs";

  if (agent.isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-36 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (agent.error || !agent.data) {
    return <ErrorCard error={agent.error ?? new Error("Agent not found")} onRetry={() => void agent.refetch()} />;
  }

  const a = agent.data;
  const snapshots = ars.data ?? [];
  const arsByRun = new Map(snapshots.map((s) => [s.eval_run_id, s.ars]));
  const latestSnapshot = [...snapshots].sort((x, y) => x.created_at.localeCompare(y.created_at)).at(-1);
  const trigger = (
    <RoleGate allow={["admin", "developer"]}>
      <TriggerEvalRunDialog agentId={a.id} versions={a.versions} />
    </RoleGate>
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold">{a.name}</h1>
          {a.description && <p className="text-sm text-muted-foreground">{a.description}</p>}
        </div>
        <RoleGate allow={["admin", "developer"]}>
          <div className="flex flex-wrap gap-2">
            <TriggerDiffRunDialog agentId={a.id} versions={a.versions} />
            <TriggerLoadRunDialog agentId={a.id} versions={a.versions} />
            <TriggerEvalRunDialog agentId={a.id} versions={a.versions} />
          </div>
        </RoleGate>
      </div>

      <AgentHealthHeader
        agentId={a.id}
        ars={latestSnapshot?.ars}
        budget={budget.data}
        driftAlerts={drift.data}
        latestRun={a.recent_runs[0]}
        loading={ars.isLoading || budget.isLoading || drift.isLoading}
      />

      <Tabs
        value={tab}
        onValueChange={(v) => setParams(v === "runs" ? {} : { tab: v }, { replace: true })}
      >
        <TabsList className="h-auto max-w-full flex-wrap justify-start">
          <TabsTrigger value="runs">Recent Runs</TabsTrigger>
          <TabsTrigger value="ars-trend">ARS Trend</TabsTrigger>
          <TabsTrigger value="drift-alerts">
            Drift Alerts{drift.data && drift.data.length > 0 ? ` (${drift.data.length})` : ""}
          </TabsTrigger>
          <TabsTrigger value="clusters">Failure Clusters</TabsTrigger>
          <TabsTrigger value="load-tests">Load Tests</TabsTrigger>
        </TabsList>

        <TabsContent value="runs" className="space-y-6">
          {a.recent_runs.length === 0 ? (
            <Card>
              <EmptyState
                icon={PlayCircle}
                title="No eval runs yet"
                description="Trigger an eval run to score this agent and get a gate verdict."
                action={trigger}
              />
            </Card>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Run</TableHead>
                  <TableHead>ARS</TableHead>
                  <TableHead>Gate</TableHead>
                  <TableHead>Triggered by</TableHead>
                  <TableHead>Completed</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {a.recent_runs.map((run) => {
                  const runArs = arsByRun.get(run.id);
                  return (
                    <TableRow key={run.id}>
                      <TableCell>
                        <Link to={`/runs/${run.id}`} className="font-mono text-xs hover:underline">
                          {shortId(run.id)}
                        </Link>
                      </TableCell>
                      <TableCell className={cn("font-mono", arsColor(runArs))}>
                        {formatAr(runArs)}
                      </TableCell>
                      <TableCell>
                        <GateBadge passed={run.gate_result?.passed} status={run.status} />
                      </TableCell>
                      <TableCell>{run.triggered_by}</TableCell>
                      <TableCell className="text-muted-foreground" title={formatDateTime(run.completed_at)}>
                        {timeAgo(run.completed_at)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}

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
                {a.versions.map((v) => (
                  <TableRow key={v.id}>
                    <TableCell className="font-medium">{v.version_label}</TableCell>
                    <TableCell>{v.model_name}</TableCell>
                    <TableCell className="font-mono text-xs">{v.content_hash.slice(0, 12)}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(v.created_at).toLocaleDateString()}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </section>
        </TabsContent>

        <TabsContent value="ars-trend" className="space-y-4">
          {ars.error ? (
            <ErrorCard error={ars.error} onRetry={() => void ars.refetch()} />
          ) : (
            <ArsTrendChart snapshots={snapshots} />
          )}
        </TabsContent>

        <TabsContent value="drift-alerts">
          {drift.error ? (
            <ErrorCard error={drift.error} onRetry={() => void drift.refetch()} />
          ) : (
            <DriftAlertsList alerts={drift.data ?? []} agentId={a.id} />
          )}
        </TabsContent>

        <TabsContent value="clusters">
          <FailureClustersTab agentId={a.id} />
        </TabsContent>

        <TabsContent value="load-tests">
          <LoadTestsTab
            agentId={a.id}
            trigger={
              <RoleGate allow={["admin", "developer"]}>
                <TriggerLoadRunDialog agentId={a.id} versions={a.versions} />
              </RoleGate>
            }
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
