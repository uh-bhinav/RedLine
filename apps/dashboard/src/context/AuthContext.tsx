import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import {
  AuthRequiredError,
  apiFetch,
  hasStoredSession,
  loginRequest,
  logoutRequest,
} from "@/lib/apiClient";
import type { MeResponse, Role } from "@/lib/types";

interface AuthContextValue {
  user: MeResponse | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  role: Role | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<MeResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const fetchMe = useCallback(async () => {
    const me = await apiFetch<MeResponse>("/auth/me");
    setUser(me);
    return me;
  }, []);

  useEffect(() => {
    // On mount: if a refresh token is already in storage (page reload, new
    // tab), proactively fetch the current user. apiFetch's own 401->refresh
    // handling takes care of exchanging the refresh token for a fresh access
    // token on that first call -- no need to duplicate the refresh call here.
    let cancelled = false;

    async function init() {
      if (!hasStoredSession()) {
        setIsLoading(false);
        return;
      }
      try {
        await fetchMe();
      } catch (err) {
        if (!(err instanceof AuthRequiredError)) {
          // Unexpected error (network, 500) -- fail closed to /login rather
          // than silently retrying, but don't swallow it entirely.
          console.error("Failed to resolve current session:", err);
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void init();
    return () => {
      cancelled = true;
    };
  }, [fetchMe]);

  const login = useCallback(
    async (email: string, password: string) => {
      await loginRequest(email, password);
      await fetchMe();
    },
    [fetchMe],
  );

  const logout = useCallback(async () => {
    await logoutRequest();
    setUser(null);
  }, []);

  const value: AuthContextValue = {
    user,
    isAuthenticated: user !== null,
    isLoading,
    role: (user?.role as Role | undefined) ?? null,
    login,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === undefined) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
