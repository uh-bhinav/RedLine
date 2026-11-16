import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { ArsSnapshotItem } from "@/lib/types";

export function useArsHistory(agentId: string | undefined) {
  return useQuery({
    queryKey: ["ars-history", agentId],
    queryFn: () => apiFetch<ArsSnapshotItem[]>(`/dashboard/agents/${agentId}/ars-history`),
    enabled: agentId !== undefined,
  });
}
