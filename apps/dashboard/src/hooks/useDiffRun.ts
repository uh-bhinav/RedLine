import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { DiffRunResponse } from "@/lib/types";

export function useDiffRun(diffId: string | undefined) {
  return useQuery({
    queryKey: ["diff-run", diffId],
    queryFn: () => apiFetch<DiffRunResponse>(`/diff-runs/${diffId}`),
    enabled: diffId !== undefined,
  });
}
