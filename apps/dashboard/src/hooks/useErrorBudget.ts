import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { ErrorBudgetResponse } from "@/lib/types";

export function useErrorBudget(agentId: string | undefined) {
  return useQuery({
    queryKey: ["error-budget", agentId],
    queryFn: () => apiFetch<ErrorBudgetResponse>(`/dashboard/agents/${agentId}/error-budget`),
    enabled: agentId !== undefined,
  });
}
