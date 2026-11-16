import { QueryClient } from "@tanstack/react-query";
import { AuthRequiredError } from "./apiClient";

export const queryClient = new QueryClient({
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
