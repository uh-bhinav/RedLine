import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { RunListItem } from "@/lib/types";
import { ACTIVE_STATUSES } from "@/lib/utils";

/** GET /dashboard/runs -- cross-agent eval runs; polls every 3s while any run is pending/running. */
export function useRuns() {
  return useQuery({
    queryKey: ["runs"],
    queryFn: () => apiFetch<RunListItem[]>("/dashboard/runs"),
    refetchInterval: (query) =>
      query.state.data?.some((r) => ACTIVE_STATUSES.has(r.status)) ? 3000 : false,
  });
}
