import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import type { ErrorBudgetResponse } from "@/lib/types";

export function ErrorBudgetGauge({ budget }: { budget: ErrorBudgetResponse }) {
  const remainingPct = Math.round(
    (budget.budget_remaining_pct / Math.max(budget.error_budget_pct, 0.0001)) * 100,
  );

  return (
    <div
      className={cn(
        "rounded-lg border p-4",
        budget.exhausted && "border-destructive/30 bg-destructive/10",
      )}
    >
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-medium">
          {budget.exhausted ? (
            <AlertTriangle className="h-4 w-4 text-destructive" />
          ) : (
            <CheckCircle2 className="h-4 w-4 text-green-600" />
          )}
          Error budget
        </div>
        <span className="text-sm text-muted-foreground">
          target ARS ≥ {budget.target_ars.toFixed(2)}
        </span>
      </div>
      <Progress value={Math.max(0, Math.min(100, remainingPct))} className="h-2" />
      <p className="mt-2 text-sm text-muted-foreground">{budget.detail}</p>
    </div>
  );
}
