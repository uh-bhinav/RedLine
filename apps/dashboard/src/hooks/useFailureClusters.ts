import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { FailureClusterResponse } from "@/lib/types";

export function useRunMining(agentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<FailureClusterResponse[]>(`/mining/${agentId}/run`, { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["candidate-cases", agentId] });
    },
  });
}
