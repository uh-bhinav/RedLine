import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiClient";
import type { ApiKeyCreate, ApiKeyCreated, ApiKeyItem } from "@/lib/types";

/** GET /auth/api-keys -- masked list (raw keys are never retrievable). */
export function useApiKeys() {
  return useQuery({
    queryKey: ["api-keys"],
    queryFn: () => apiFetch<ApiKeyItem[]>("/auth/api-keys"),
  });
}

/** POST /auth/api-keys -- the response carries the raw `key` exactly once. */
export function useCreateApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ApiKeyCreate) =>
      apiFetch<ApiKeyCreated>("/auth/api-keys", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });
}

/** DELETE /auth/api-keys/{id} -- returns the (now revoked) masked item. */
export function useRevokeApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) =>
      apiFetch<ApiKeyItem>(`/auth/api-keys/${keyId}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });
}
