import { MutationCache, QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError, AuthRequiredError, ForbiddenError } from "./apiClient";

/** Best-effort human message: the API returns `{"detail": ...}` JSON bodies as text. */
export function errorMessage(error: unknown): string {
  if (error instanceof ForbiddenError) return "You do not have permission to do that.";
  if (error instanceof ApiError) {
    try {
      const body = JSON.parse(error.message) as { detail?: unknown };
      if (typeof body.detail === "string") return body.detail;
      if (Array.isArray(body.detail)) {
        return body.detail
          .map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
          .join("; ");
      }
    } catch {
      /* not JSON */
    }
    return error.message || `Request failed (${error.status})`;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

export const queryClient = new QueryClient({
  // Every mutation failure surfaces as a toast unless the mutation sets
  // `meta: { silent: true }` (e.g. a form that renders its own inline error).
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) => {
      if (mutation.meta?.silent) return;
      // AuthContext/RequireAuth redirect on auth failure; a toast would be noise.
      if (error instanceof AuthRequiredError) return;
      toast.error(errorMessage(error));
    },
  }),
  defaultOptions: {
    queries: {
      // Don't burn retries on an auth failure -- AuthContext/RequireAuth
      // handles that by redirecting to /login, retrying just delays it.
      retry: (failureCount, error) => {
        if (error instanceof AuthRequiredError) return false;
        return failureCount < 2;
      },
    },
  },
});
