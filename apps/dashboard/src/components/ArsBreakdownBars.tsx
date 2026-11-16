import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { ArsBreakdown } from "@/lib/types";
import { ARS_TARGET, ARS_WARN, arsHex } from "@/lib/utils";

const BARS: { key: keyof Omit<ArsBreakdown, "ars">; label: string; weight: number }[] = [
  { key: "correctness", label: "Correctness", weight: 40 },
  { key: "safety", label: "Safety", weight: 20 },
  { key: "latency", label: "Latency", weight: 20 },
  { key: "cost", label: "Cost", weight: 20 },
];

const barColor = (v: number) =>
  v >= ARS_TARGET ? "bg-green-500" : v >= ARS_WARN ? "bg-amber-500" : "bg-red-500";

/** Weighted ARS sub-score bars + composite, from RunDetailResponse.ars. */
export function ArsBreakdownBars({ ars }: { ars: ArsBreakdown }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>ARS Breakdown</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {BARS.map((b) => (
          <div key={b.key} className="grid grid-cols-[88px_1fr_auto] items-center gap-3 text-sm">
            <span>{b.label}</span>
            <Progress value={ars[b.key] * 100} className="h-2" indicatorClassName={barColor(ars[b.key])} />
            <span className="w-32 text-right font-mono text-xs">
              {ars[b.key].toFixed(3)} <span className="text-muted-foreground">({b.weight}%)</span>
            </span>
          </div>
        ))}
        <div className="flex items-center justify-between border-t pt-3 text-sm font-semibold">
          <span>ARS (composite)</span>
          <span className="font-mono text-base" style={{ color: arsHex(ars.ars) }}>
            {ars.ars.toFixed(3)}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
