import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { AgentListItem } from "@/lib/types";

export function useAgents() {
  return useQuery({
    queryKey: ["agents"],
    queryFn: () => apiFetch<AgentListItem[]>("/dashboard/agents"),
  });
}
