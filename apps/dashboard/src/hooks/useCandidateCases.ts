import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { CandidateCaseResponse } from "@/lib/types";

export function useCandidateCases(agentId: string | undefined, status = "pending") {
  return useQuery({
    queryKey: ["candidate-cases", agentId, status],
    queryFn: () =>
      apiFetch<CandidateCaseResponse[]>(
        `/mining/candidates?agent_id=${agentId}&status=${status}`,
      ),
    enabled: agentId !== undefined,
  });
}

export function useReviewCandidate(agentId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ candidateId, action }: { candidateId: string; action: "approve" | "reject" }) =>
      apiFetch<CandidateCaseResponse>(`/mining/candidates/${candidateId}/${action}`, {
        method: "POST",
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["candidate-cases", agentId] });
    },
  });
}
