import { AlertTriangle, RefreshCw } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/queryClient";

/** Inline query-error card with an optional Retry button (pass `() => query.refetch()`). */
export function ErrorCard({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <Alert variant="destructive" className="flex items-center gap-3">
      <AlertTriangle className="!static size-4 shrink-0" />
      <div className="flex-1 text-sm">{errorMessage(error)}</div>
      {onRetry && (
        <Button size="sm" variant="outline" onClick={onRetry}>
          <RefreshCw />
          Retry
        </Button>
      )}
    </Alert>
  );
}
