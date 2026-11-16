import { ArrowRight, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { EmptyState } from "@/components/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { DriftAlertItem } from "@/lib/types";
import { cn, formatDateTime } from "@/lib/utils";

/**
 * Where "Investigate" goes. Behaviour-drift alerts are BehaviorDiff rows, so
 * their id IS the diff id (/diffs/:id). The alert payload carries no
 * `diff_run_id` for model drift, so those fall back to the agent's ARS tab.
 */
export function investigateLink(alert: DriftAlertItem, agentId: string): string {
  const withDiff = alert as DriftAlertItem & { diff_run_id?: string | null };
  if (withDiff.diff_run_id) return `/diffs/${withDiff.diff_run_id}`;
  if (alert.drift_type === "behavior") return `/diffs/${alert.id}`;
  return `/agent/${agentId}?tab=ars-trend`;
}

/** Drift alerts as cards: red left border for model drift, amber otherwise. */
export function DriftAlertsList({
  alerts,
  agentId,
}: {
  alerts: DriftAlertItem[];
  agentId: string;
}) {
  if (alerts.length === 0) {
    return (
      <EmptyState
        icon={ShieldCheck}
        tone="success"
        title="No drift detected"
        description="Model and behavior are stable against the baseline. Alerts appear here when a model change or silent behavior drift is found."
      />
    );
  }

  return (
    <div className="space-y-3">
      {alerts.map((alert) => {
        const isModel = alert.drift_type === "model";
        const delta = alert.current_value - alert.baseline_value;
        return (
          <Card
            key={`${alert.drift_type}-${alert.id}`}
            className={cn("border-l-4 p-4", isModel ? "border-l-red-500" : "border-l-amber-500")}
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={isModel ? "fail" : "warn"}>
                {isModel ? "model drift" : "behavior drift"}
              </Badge>
              <span className="text-sm font-semibold">{alert.metric_label.replace("_", " ")}</span>
            </div>
            <p className="mt-2 font-mono text-sm">
              Baseline {alert.baseline_value.toFixed(3)} <ArrowRight className="inline size-3" />{" "}
              Current {alert.current_value.toFixed(3)}{" "}
              <span className="text-red-600 dark:text-red-400">
                (delta {delta >= 0 ? "+" : ""}
                {delta.toFixed(3)})
              </span>
            </p>
            {alert.detail && (
              <p className="mt-1 text-sm text-muted-foreground">&ldquo;{alert.detail}&rdquo;</p>
            )}
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>Detected: {formatDateTime(alert.created_at)}</span>
              <Link
                to={investigateLink(alert, agentId)}
                className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
              >
                Investigate <ArrowRight className="size-3.5" />
              </Link>
            </div>
          </Card>
        );
      })}
    </div>
  );
}
