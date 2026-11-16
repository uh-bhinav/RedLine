import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { TraceEventItem } from "@/lib/types";

export function useTraces(runId: string | undefined) {
  return useQuery({
    queryKey: ["traces", runId],
    queryFn: () => apiFetch<TraceEventItem[]>(`/dashboard/runs/${runId}/traces`),
    enabled: runId !== undefined,
  });
}
