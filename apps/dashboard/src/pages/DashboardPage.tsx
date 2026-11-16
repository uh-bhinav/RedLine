import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { Activity, Bot, ShieldCheck, Wallet } from "lucide-react";
import { AgentsTable, AgentsTableSkeleton } from "@/components/AgentsTable";
import { AlertStrip, type StripAlert } from "@/components/AlertStrip";
import { CodeBlock } from "@/components/CodeBlock";
import { EmptyState } from "@/components/EmptyState";
import { ErrorCard } from "@/components/ErrorCard";
import { SummaryCard } from "@/components/SummaryCard";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/context/AuthContext";
import { useAgents } from "@/hooks/useAgents";
import { useDiffs } from "@/hooks/useDiffs";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { usePlatformSummary } from "@/hooks/usePlatformSummary";
import { apiFetch } from "@/lib/apiClient";
import type { ErrorBudgetResponse } from "@/lib/types";
import { ARS_TARGET, greeting } from "@/lib/utils";

export function DashboardPage() {
  useDocumentTitle("Dashboard");
  const { user } = useAuth();
  const summary = usePlatformSummary();
  const agents = useAgents();
  const diffs = useDiffs();

  // Same query key as useErrorBudget, so the cache is shared with the agent page.
  const budgets = useQueries({
    queries: (agents.data ?? []).map((a) => ({
      queryKey: ["error-budget", a.id],
      queryFn: () => apiFetch<ErrorBudgetResponse>(`/dashboard/agents/${a.id}/error-budget`),
    })),
  });
  const budgetSig = budgets.map((b) => b.data?.exhausted ?? "").join(",");

  const alerts = useMemo<StripAlert[]>(() => {
    const agentAlerts: StripAlert[] = [];
    // One alert per agent (most severe only): budget > gate > ARS.
    (agents.data ?? []).forEach((a, i) => {
      const href = `/agent/${a.id}`;
      if (budgets[i]?.data?.exhausted) {
        agentAlerts.push({ id: `${a.id}:budget`, message: `${a.name} - Error budget exhausted`, href, tone: "bad" });
      } else if (a.latest_run?.gate_passed === false) {
        agentAlerts.push({ id: `${a.id}:gate`, message: `${a.name} - Latest gate failing`, href, tone: "bad" });
      } else if (a.latest_ars != null && a.latest_ars < ARS_TARGET) {
        agentAlerts.push({
          id: `${a.id}:ars`,
          message: `${a.name} - ARS below ${ARS_TARGET} (${a.latest_ars.toFixed(3)})`,
          href,
          tone: "warn",
        });
      }
    });
    // Silent-drift alerts: one per agent (diffs come newest-first). They are a
    // different kind of signal from budget/gate, so they are never crowded out
    // by a long list of budget/gate alerts: order is worst agent alert, then
    // drift alerts, then the remaining agent alerts.
    const seen = new Set<string>();
    const driftAlerts: StripAlert[] = [];
    (diffs.data ?? [])
      .filter((d) => d.classification === "silent_drift")
      .forEach((d) => {
        if (seen.has(d.agent_name)) return;
        seen.add(d.agent_name);
        driftAlerts.push({
          id: `${d.id}:drift`,
          message: `${d.agent_name} - Silent behaviour drift detected`,
          href: `/diffs/${d.id}`,
          tone: "warn",
        });
      });
    const [first, ...rest] = agentAlerts;
    return first ? [first, ...driftAlerts, ...rest] : driftAlerts;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents.data, diffs.data, budgetSig]);

  const s = summary.data;
  const passRate = s?.gate_pass_rate;
  const passTone = passRate == null ? "default" : passRate >= 0.7 ? "good" : passRate >= 0.5 ? "warn" : "bad";
  const budgetTone =
    !s || s.total_budget_count === 0
      ? "default"
      : s.healthy_budget_count === s.total_budget_count
        ? "good"
        : s.healthy_budget_count === 0
          ? "bad"
          : "warn";

  const who = user?.tenant_name || user?.email || "";
  const today = new Date().toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">
          {greeting()}
          {who ? `, ${who}` : ""}
        </h1>
        <p className="text-sm text-muted-foreground">{today}</p>
      </div>

      {summary.isLoading ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      ) : summary.error ? (
        <ErrorCard error={summary.error} onRetry={() => void summary.refetch()} />
      ) : (
        s && (
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <SummaryCard index={0} icon={Bot} label="Total Agents" value={s.total_agents} />
            <SummaryCard index={1} icon={Activity} label="Runs (7d)" value={s.runs_last_7d} />
            <SummaryCard
              index={2}
              icon={ShieldCheck}
              label="Gate Pass Rate"
              tone={passTone}
              {...(passRate == null
                ? { text: "No runs yet" }
                : { value: Math.round(passRate * 100), suffix: "%" })}
            />
            <SummaryCard
              index={3}
              icon={Wallet}
              label="Budgets Healthy"
              tone={budgetTone}
              text={`${s.healthy_budget_count}/${s.total_budget_count}`}
            />
          </div>
        )
      )}

      {agents.data && <AlertStrip alerts={alerts} />}

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Agents</h2>
        {agents.isLoading ? (
          <AgentsTableSkeleton />
        ) : agents.error ? (
          <ErrorCard error={agents.error} onRetry={() => void agents.refetch()} />
        ) : agents.data && agents.data.length > 0 ? (
          <AgentsTable agents={agents.data} />
        ) : (
          <div className="rounded-lg border">
            <EmptyState
              icon={Bot}
              title="No agents registered yet"
              description="Register your first agent from the CLI, then push an eval suite and run it."
              action={
                <div className="w-full max-w-sm space-y-3 text-left">
                  <CodeBlock code="agentbench init --agent my-agent" />
                  <Button asChild variant="link" className="px-0">
                    <a
                      href="https://github.com/uh-bhinav/RedLine#quickstart"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Read the quickstart →
                    </a>
                  </Button>
                </div>
              }
            />
          </div>
        )}
      </section>
    </div>
  );
}
