import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { FailureClusterResponse } from "@/lib/types";

/** GET /mining/{agent_id}/clusters */
export function useClusters(agentId: string | undefined) {
  return useQuery({
    queryKey: ["clusters", agentId],
    queryFn: () => apiFetch<FailureClusterResponse[]>(`/mining/${agentId}/clusters`),
    enabled: agentId !== undefined,
  });
}

/** POST /mining/{agent_id}/run -- returns the freshly computed clusters. */
export function useRunMining(agentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<FailureClusterResponse[]>(`/mining/${agentId}/run`, { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["clusters", agentId] });
      void queryClient.invalidateQueries({ queryKey: ["candidate-cases", agentId] });
    },
  });
}

const dismissKey = (agentId: string) => `rl_dismissed_clusters_${agentId}`;

function readDismissed(agentId: string): string[] {
  try {
    return JSON.parse(localStorage.getItem(dismissKey(agentId)) ?? "[]") as string[];
  } catch {
    return [];
  }
}

/**
 * The backend has no cluster-dismiss endpoint, so dismissal is a client-side,
 * per-agent hidden set persisted in localStorage. `visible(clusters)` filters
 * dismissed ids; `dismiss(id)` / `restoreAll()` mutate the set.
 */
export function useDismissedClusters(agentId: string | undefined) {
  const [ids, setIds] = useState<string[]>(() => (agentId ? readDismissed(agentId) : []));

  const persist = useCallback(
    (next: string[]) => {
      setIds(next);
      if (!agentId) return;
      try {
        localStorage.setItem(dismissKey(agentId), JSON.stringify(next));
      } catch {
        /* storage unavailable */
      }
    },
    [agentId],
  );

  const dismiss = useCallback((id: string) => persist([...new Set([...ids, id])]), [ids, persist]);
  const restoreAll = useCallback(() => persist([]), [persist]);
  const visible = useCallback(
    <T extends { id: string }>(clusters: T[]) => clusters.filter((c) => !ids.includes(c.id)),
    [ids],
  );

  return { dismissedIds: ids, dismiss, restoreAll, visible };
}
