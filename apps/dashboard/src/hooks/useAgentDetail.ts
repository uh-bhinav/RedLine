import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { AgentDetailResponse } from "@/lib/types";

export function useAgentDetail(agentId: string | undefined) {
  return useQuery({
    queryKey: ["agent", agentId],
    queryFn: () => apiFetch<AgentDetailResponse>(`/dashboard/agents/${agentId}`),
    enabled: agentId !== undefined,
  });
}
