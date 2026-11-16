import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { DiffRunCreate, DiffRunResponse } from "@/lib/types";

export function useCreateDiffRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: DiffRunCreate) =>
      apiFetch<DiffRunResponse>("/diff-runs", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["diffs"] });
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}
