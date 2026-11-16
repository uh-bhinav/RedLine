import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { PlatformSummary } from "@/lib/types";

/** GET /dashboard/summary -- dashboard home KPI tiles. Stale time 30s. */
export function usePlatformSummary() {
  return useQuery({
    queryKey: ["summary"],
    queryFn: () => apiFetch<PlatformSummary>("/dashboard/summary"),
    staleTime: 30_000,
  });
}
