// Auth-aware fetch wrapper. Access token (15 min TTL) lives only in this
// module's memory -- never persisted. Refresh token (7 day TTL, rotates on
// every use) lives in localStorage, since it must survive a page reload.
//
// Single-flight refresh is load-bearing, not stylistic: the backend's
// rotate_refresh_token() treats reuse of an already-rotated refresh token as
// session hijacking and revokes ALL of that user's sessions
// (apps/api/core/auth.py). Two concurrent 401s naively calling /auth/refresh
// independently would each try to rotate the same token -- the second call
// would find it already rotated and trigger exactly that revocation. The
// `refreshPromise ??= doRefresh()` pattern below ensures every concurrent
// caller awaits the SAME in-flight refresh instead.

const REFRESH_TOKEN_KEY = "redline.refresh_token";

let accessToken: string | null = null;
let refreshPromise: Promise<string> | null = null;

export class AuthRequiredError extends Error {
  constructor(message = "Authentication required") {
    super(message);
    this.name = "AuthRequiredError";
  }
}

export class ForbiddenError extends Error {
  constructor(message = "Forbidden") {
    super(message);
    this.name = "ForbiddenError";
  }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setRefreshToken(token: string | null) {
  if (token) localStorage.setItem(REFRESH_TOKEN_KEY, token);
  else localStorage.removeItem(REFRESH_TOKEN_KEY);
}

export function clearTokens() {
  setAccessToken(null);
  setRefreshToken(null);
}

interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

async function doRefresh(): Promise<string> {
  const refresh_token = getRefreshToken();
  if (!refresh_token) throw new AuthRequiredError("no refresh token stored");

  const res = await fetch("/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token }),
  });

  if (!res.ok) {
    clearTokens();
    throw new AuthRequiredError("refresh token rejected");
  }

  const data = (await res.json()) as TokenResponse;
  setAccessToken(data.access_token);
  // The backend ROTATES the refresh token on every use -- the old one is now
  // invalid. Overwriting (never appending/ignoring) is required, or the next
  // refresh attempt reuses a dead token and triggers reuse-detection.
  setRefreshToken(data.refresh_token);
  return data.access_token;
}

export async function loginRequest(email: string, password: string): Promise<void> {
  const res = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    // Same generic message for wrong email or wrong password, matching the
    // backend's own no-enumeration behavior -- the frontend must not try to
    // guess which one was wrong.
    throw new ApiError(res.status, "invalid credentials");
  }
  const data = (await res.json()) as TokenResponse;
  setAccessToken(data.access_token);
  setRefreshToken(data.refresh_token);
}

export async function logoutRequest(): Promise<void> {
  const refresh_token = getRefreshToken();
  if (refresh_token) {
    try {
      await fetch("/auth/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token }),
      });
    } catch {
      // Best-effort -- clear local tokens regardless of whether the server
      // call succeeded (e.g. network down should not trap the user logged in).
    }
  }
  clearTokens();
}

/** True if a refresh token exists in storage -- used at app mount to decide
 * whether to attempt a proactive refresh before rendering anything. */
export function hasStoredSession(): boolean {
  return getRefreshToken() !== null;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const doFetch = (token: string | null) =>
    fetch(path, {
      ...init,
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });

  const refreshOnce = () => {
    refreshPromise ??= doRefresh().finally(() => {
      refreshPromise = null;
    });
    return refreshPromise;
  };

  // No in-memory access token (fresh page load) but a refresh token exists:
  // refresh FIRST (single-flight) so we never fire a request we know will 401.
  let token = accessToken;
  if (!token && getRefreshToken()) token = await refreshOnce();

  let res = await doFetch(token);

  if (res.status === 401) {
    res = await doFetch(await refreshOnce());
  }

  if (res.status === 401) throw new AuthRequiredError();
  if (res.status === 403) throw new ForbiddenError();
  if (!res.ok) throw new ApiError(res.status, await res.text());
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
