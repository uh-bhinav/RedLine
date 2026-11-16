import { CheckCircle2, ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ARSRing } from "@/components/ARSRing";
import { budgetSentence, budgetStatus } from "@/components/ErrorBudgetGauge";
import { GateBadge } from "@/components/GateBadge";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { DriftAlertItem, ErrorBudgetResponse, EvalRunSummary } from "@/lib/types";
import { arsColor, arsLabel, cn } from "@/lib/utils";
import { investigateLink } from "@/components/DriftAlertsList";

function Cell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-2 p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {title}
      </div>
      {children}
    </div>
  );
}

const BUDGET_VARIANT = { healthy: "pass", at_risk: "warn", frozen: "fail" } as const;
const BUDGET_LABEL = { healthy: "HEALTHY", at_risk: "AT RISK", frozen: "FROZEN" } as const;

/**
 * Four-cell health strip: ARS ring, error-budget pill, drift status, gate.
 * 2x2 on mobile, 4 columns from md up. Any input may still be loading (undefined).
 */
export function AgentHealthHeader({
  agentId,
  ars,
  budget,
  driftAlerts,
  latestRun,
  loading,
}: {
  agentId: string;
  ars: number | null | undefined;
  budget: ErrorBudgetResponse | undefined;
  driftAlerts: DriftAlertItem[] | undefined;
  latestRun: EvalRunSummary | undefined;
  loading?: boolean;
}) {
  if (loading) return <Skeleton className="h-36 w-full" />;

  const behavior = (driftAlerts ?? []).filter((a) => a.drift_type === "behavior");
  const model = (driftAlerts ?? []).filter((a) => a.drift_type === "model");
  const drifting = behavior.length + model.length > 0;
  const firstAlert = behavior[0] ?? model[0];
  // The backend states the affected case count only in the detail text ("across 6 case(s)").
  const caseCount = behavior.reduce((n, a) => {
    const m = /across (\d+) case/.exec(a.detail);
    return n + (m ? Number(m[1]) : 1);
  }, 0);
  const driftText =
    behavior.length > 0
      ? `SILENT_DRIFT on ${caseCount} case${caseCount === 1 ? "" : "s"}`
      : `Model drift: ${model.length} alert${model.length === 1 ? "" : "s"}`;

  const gate = latestRun?.gate_result;

  return (
    <Card className="grid grid-cols-2 divide-x divide-y md:grid-cols-4 md:divide-y-0 [&>*:nth-child(odd)]:border-l-0 md:[&>*:nth-child(odd)]:border-l [&>*:first-child]:border-l-0 [&>*:nth-child(-n+2)]:border-t-0 md:[&>*]:border-t-0">
      <Cell title="ARS Score">
        <div className="flex items-center gap-3">
          <ARSRing ars={ars} />
          <div className={cn("text-sm font-semibold", arsColor(ars))}>{arsLabel(ars)}</div>
        </div>
      </Cell>

      <Cell title="Error Budget">
        {budget ? (
          <>
            <Badge variant={BUDGET_VARIANT[budgetStatus(budget)]} className="w-fit px-3 py-1 text-sm">
              {BUDGET_LABEL[budgetStatus(budget)]}
            </Badge>
            <p className="text-sm text-muted-foreground">{budgetSentence(budget)}</p>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">No budget data yet</p>
        )}
      </Cell>

      <Cell title="Drift Status">
        {drifting && firstAlert ? (
          <>
            <Badge variant="fail" className="w-fit px-3 py-1 text-sm">
              <ShieldAlert className="size-3.5" />
              ALERT
            </Badge>
            <Link
              to={investigateLink(firstAlert, agentId)}
              className="text-sm text-red-600 hover:underline dark:text-red-400"
            >
              {driftText}
            </Link>
          </>
        ) : (
          <>
            <Badge variant="pass" className="w-fit px-3 py-1 text-sm">
              <CheckCircle2 className="size-3.5" />
              CLEAN
            </Badge>
            <p className="text-sm text-muted-foreground">No drift detected</p>
          </>
        )}
      </Cell>

      <Cell title="Gate">
        {latestRun ? (
          <>
            <GateBadge passed={gate?.passed} status={latestRun.status} />
            <p className="text-sm text-muted-foreground">
              {gate
                ? gate.passed
                  ? "All gate checks passed"
                  : `${gate.reasons.length} reason${gate.reasons.length === 1 ? "" : "s"}`
                : latestRun.status}
            </p>
            <Link to={`/runs/${latestRun.id}`} className="text-xs text-primary hover:underline">
              View latest run
            </Link>
          </>
        ) : (
          <>
            <GateBadge passed={null} />
            <p className="text-sm text-muted-foreground">No eval runs yet</p>
          </>
        )}
      </Cell>
    </Card>
  );
}
