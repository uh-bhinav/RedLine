import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { RunDetailResponse } from "@/lib/types";

const ACTIVE_STATUSES = new Set(["pending", "running"]);

export function useRunDetail(runId: string | undefined) {
  return useQuery({
    queryKey: ["run", runId],
    queryFn: () => apiFetch<RunDetailResponse>(`/dashboard/runs/${runId}`),
    enabled: runId !== undefined,
    // Poll a still-running eval every 3s; stop once it reaches a terminal
    // status. This is the concrete case ADR-006 cites for choosing TanStack
    // Query -- v1 had no live-updating "running" state at all.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && ACTIVE_STATUSES.has(status) ? 3000 : false;
    },
  });
}
