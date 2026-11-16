import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { EvalRunCreate, EvalRunSummary } from "@/lib/types";

export function useCreateEvalRun(agentId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: EvalRunCreate) =>
      apiFetch<EvalRunSummary>("/eval-runs", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agent", agentId] });
    },
  });
}
