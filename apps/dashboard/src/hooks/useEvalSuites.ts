import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { EvalSuiteSummary } from "@/lib/types";

export function useEvalSuites(agentId: string | undefined) {
  return useQuery({
    queryKey: ["eval-suites", agentId],
    queryFn: () => apiFetch<EvalSuiteSummary[]>(`/eval-suites?agent_id=${agentId}`),
    enabled: agentId !== undefined,
  });
}
