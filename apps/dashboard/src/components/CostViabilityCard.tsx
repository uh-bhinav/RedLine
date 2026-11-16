import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, formatCost } from "@/lib/utils";

/** Linear cost projection for a load run (viable while 10x load stays <= $10/hour). */
export function CostViabilityCard({
  costPerHourUsd,
  concurrency,
}: {
  costPerHourUsd: number | null | undefined;
  concurrency: number;
}) {
  const cph = costPerHourUsd ?? 0;
  const viable = cph * 10 <= 10;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Cost Analysis</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5 font-mono text-sm">
        <div className="flex justify-between">
          <span>Current load ({concurrency} users):</span>
          <span>{formatCost(cph)}/hour</span>
        </div>
        <div className="flex justify-between">
          <span>Projected at 10× load:</span>
          <span>~{formatCost(cph * 10)}/hour</span>
        </div>
        <div className="flex justify-between">
          <span>Projected at 100× load:</span>
          <span>~{formatCost(cph * 100)}/hour</span>
        </div>
        <p
          className={cn(
            "pt-2 font-sans font-medium",
            viable ? "text-green-600 dark:text-green-400" : "text-amber-600 dark:text-amber-400",
          )}
        >
          {viable
            ? "● Financially viable at current scale"
            : `○ Review before exceeding ${concurrency} concurrent users`}
        </p>
        <p className="font-sans text-xs text-muted-foreground">
          Linear projection — an estimate, not a capacity model.
        </p>
      </CardContent>
    </Card>
  );
}
