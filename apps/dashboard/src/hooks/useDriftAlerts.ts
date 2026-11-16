import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { DriftAlertItem } from "@/lib/types";

export function useDriftAlerts(agentId: string | undefined) {
  return useQuery({
    queryKey: ["drift-alerts", agentId],
    queryFn: () => apiFetch<DriftAlertItem[]>(`/dashboard/agents/${agentId}/drift-alerts`),
    enabled: agentId !== undefined,
  });
}
