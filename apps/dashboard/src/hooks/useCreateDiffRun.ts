import { useMutation } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { DiffRunCreate, DiffRunResponse } from "@/lib/types";

export function useCreateDiffRun() {
  return useMutation({
    mutationFn: (payload: DiffRunCreate) =>
      apiFetch<DiffRunResponse>("/diff-runs", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
  });
}
