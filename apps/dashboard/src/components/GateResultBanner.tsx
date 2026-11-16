import { AlertCircle, CheckCircle2, Clock, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { GateResult } from "@/lib/types";

interface GateResultBannerProps {
  gateResult: GateResult | null;
  status: string;
  variant?: "full" | "badge";
}

function statusMeta(gateResult: GateResult | null, status: string) {
  if (status !== "completed") {
    return {
      label: status === "failed" ? "ERROR" : status.toUpperCase(),
      tone: status === "failed" ? "destructive" : "muted",
      Icon: status === "failed" ? AlertCircle : Clock,
    } as const;
  }
  if (gateResult === null) {
    return { label: "NO GATE RESULT", tone: "muted", Icon: AlertCircle } as const;
  }
  return gateResult.passed
    ? ({ label: "GATE PASSED", tone: "success", Icon: CheckCircle2 } as const)
    : ({ label: "GATE FAILED", tone: "destructive", Icon: XCircle } as const);
}

const TONE_BADGE_CLASSES: Record<string, string> = {
  success: "bg-green-100 text-green-800 hover:bg-green-100 dark:bg-green-900/40 dark:text-green-300",
  destructive: "",
  muted: "bg-muted text-muted-foreground hover:bg-muted",
};

const TONE_BANNER_CLASSES: Record<string, string> = {
  success: "border-green-200 bg-green-50 text-green-900 dark:border-green-900 dark:bg-green-950 dark:text-green-100",
  destructive: "border-destructive/30 bg-destructive/10 text-destructive-foreground",
  muted: "border-border bg-muted text-muted-foreground",
};

export function GateResultBanner({ gateResult, status, variant = "full" }: GateResultBannerProps) {
  const { label, tone, Icon } = statusMeta(gateResult, status);

  if (variant === "badge") {
    return (
      <Badge
        variant={tone === "destructive" ? "destructive" : "outline"}
        className={cn("gap-1", TONE_BADGE_CLASSES[tone])}
      >
        <Icon className="h-3 w-3" />
        {label}
      </Badge>
    );
  }

  return (
    <div className={cn("rounded-lg border p-4", TONE_BANNER_CLASSES[tone])}>
      <div className="flex items-center gap-2 font-semibold">
        <Icon className="h-5 w-5" />
        {label}
      </div>
      {gateResult && gateResult.reasons.length > 0 && (
        <ul className="mt-2 list-disc space-y-1 pl-6 text-sm">
          {gateResult.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
