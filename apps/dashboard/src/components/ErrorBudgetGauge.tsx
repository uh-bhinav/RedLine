import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { ErrorBudgetResponse } from "@/lib/types";

export type BudgetStatus = "healthy" | "at_risk" | "frozen";

/** exhausted -> frozen; any breach in the window -> at risk; else healthy. */
export function budgetStatus(b: ErrorBudgetResponse): BudgetStatus {
  if (b.exhausted) return "frozen";
  return b.breaches > 0 ? "at_risk" : "healthy";
}

const STYLE: Record<BudgetStatus, { label: string; variant: "pass" | "warn" | "fail" }> = {
  healthy: { label: "HEALTHY", variant: "pass" },
  at_risk: { label: "AT RISK", variant: "warn" },
  frozen: { label: "FROZEN", variant: "fail" },
};

export function budgetSentence(b: ErrorBudgetResponse): string {
  const status = budgetStatus(b);
  const above = Math.max(b.window_size - b.breaches, 0);
  if (status === "frozen")
    return `DEPLOYMENTS FROZEN — ${b.breaches}/${b.window_size} runs below target`;
  if (status === "at_risk")
    return `${above}/${b.window_size} runs above target (${b.breaches} breached)`;
  return `${above}/${b.window_size} runs above target`;
}

/** Three-state pill, the one-line sentence and a per-run window strip. */
export function ErrorBudgetGauge({ budget }: { budget: ErrorBudgetResponse }) {
  const status = budgetStatus(budget);
  const s = STYLE[status];
  const window = Math.max(budget.window_size, 0);
  return (
    <div
      className={cn(
        "space-y-2 rounded-lg border p-4",
        status === "frozen" && "border-destructive/30 bg-destructive/10",
      )}
    >
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">Error budget</div>
        <span className="text-xs text-muted-foreground">
          target ARS ≥ {budget.target_ars.toFixed(2)}
        </span>
      </div>
      <Badge variant={s.variant} className="px-3 py-1 text-sm">
        {s.label}
      </Badge>
      <p className="text-sm text-muted-foreground">{budgetSentence(budget)}</p>
      <div className="flex gap-1" aria-hidden>
        {Array.from({ length: window }).map((_, i) => (
          <span
            key={i}
            className={cn(
              "h-1.5 flex-1 rounded-full",
              i < budget.breaches ? "bg-red-500" : "bg-green-500",
            )}
          />
        ))}
      </div>
      <p className="text-xs text-muted-foreground">{budget.detail}</p>
    </div>
  );
}
