import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { LoadRunCreate, LoadRunResponse, LoadRunSummary } from "@/lib/types";

export function useLoadRuns(agentId: string | undefined) {
  return useQuery({
    queryKey: ["load-runs", agentId],
    queryFn: () => apiFetch<LoadRunSummary[]>(`/dashboard/agents/${agentId}/load-runs`),
    enabled: agentId !== undefined,
  });
}

export function useLoadRunDetail(loadRunId: string | undefined) {
  return useQuery({
    queryKey: ["load-run", loadRunId],
    queryFn: () => apiFetch<LoadRunResponse>(`/load-runs/${loadRunId}`),
    enabled: loadRunId !== undefined,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "running" ? 3000 : false;
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
      void queryClient.invalidateQueries({ queryKey: ["load-runs", agentId] });
    },
  });
}
