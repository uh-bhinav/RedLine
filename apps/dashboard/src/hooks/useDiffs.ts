import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { DiffListItem } from "@/lib/types";

/** GET /dashboard/diffs -- cross-agent behaviour diffs (always terminal; no polling). */
export function useDiffs() {
  return useQuery({
    queryKey: ["diffs"],
    queryFn: () => apiFetch<DiffListItem[]>("/dashboard/diffs"),
  });
}
