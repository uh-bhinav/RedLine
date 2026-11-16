import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";

/**
 * Compact PASS / FAIL / RUNNING / QUEUED / ERROR / NO RUNS badge for list rows.
 * `passed` is gate_passed from the list endpoints; `status` is the run status.
 */
export function GateBadge({
  passed,
  status,
}: {
  passed: boolean | null | undefined;
  status?: string;
}) {
  if (status === "pending" || status === "running") {
    return (
      <Badge variant="warn">
        <Loader2 className="size-3 animate-spin" />
        {status === "running" ? "RUNNING" : "QUEUED"}
      </Badge>
    );
  }
  if (status === "failed") {
    return (
      <Badge variant="fail">
        <XCircle className="size-3" />
        ERROR
      </Badge>
    );
  }
  if (passed == null) return <Badge variant="secondary">NO RUNS</Badge>;
  return passed ? (
    <Badge variant="pass">
      <CheckCircle2 className="size-3" />
      PASS
    </Badge>
  ) : (
    <Badge variant="fail">
      <XCircle className="size-3" />
      FAIL
    </Badge>
  );
}
