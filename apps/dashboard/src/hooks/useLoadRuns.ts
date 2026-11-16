import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type {
  LoadRunCreate,
  LoadRunListItem,
  LoadRunResponse,
  LoadRunSummary,
} from "@/lib/types";
import { ACTIVE_STATUSES } from "@/lib/utils";

/** Per-agent load runs (agent detail tab). */
export function useLoadRuns(agentId: string | undefined) {
  return useQuery({
    queryKey: ["load-runs", agentId],
    queryFn: () => apiFetch<LoadRunSummary[]>(`/dashboard/agents/${agentId}/load-runs`),
    enabled: agentId !== undefined,
  });
}

/** GET /dashboard/load-runs -- cross-agent list; polls while any run is active. */
export function useAllLoadRuns() {
  return useQuery({
    queryKey: ["load-runs", "all"],
    queryFn: () => apiFetch<LoadRunListItem[]>("/dashboard/load-runs"),
    refetchInterval: (query) =>
      query.state.data?.some((r) => ACTIVE_STATUSES.has(r.status)) ? 3000 : false,
  });
}

export function useLoadRunDetail(loadRunId: string | undefined) {
  return useQuery({
    queryKey: ["load-run", loadRunId],
    queryFn: () => apiFetch<LoadRunResponse>(`/load-runs/${loadRunId}`),
    enabled: loadRunId !== undefined,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && ACTIVE_STATUSES.has(status) ? 3000 : false;
    },
  });
}

export function useCreateLoadRun(agentId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: LoadRunCreate) =>
      apiFetch<LoadRunResponse>("/load-runs", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      // Prefix match: covers ["load-runs", agentId] and ["load-runs", "all"].
      void queryClient.invalidateQueries({ queryKey: ["load-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["agent", agentId] });
    },
  });
}
