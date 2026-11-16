import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthRequiredError, apiFetch, clearTokens, setRefreshToken } from "./apiClient";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("apiFetch single-flight refresh", () => {
  beforeEach(() => {
    localStorage.clear();
    clearTokens();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("triggers exactly one /auth/refresh call for two concurrent 401s", async () => {
    setRefreshToken("stored-refresh-token");

    let refreshCalls = 0;

    // Simulate: first attempt on each concurrent call always 401s (expired
    // access token), forcing both through the refresh path.
    let firstAttempt = true;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url === "/auth/refresh") {
          refreshCalls += 1;
          return jsonResponse({
            access_token: "new-access-token",
            refresh_token: "new-refresh-token",
            token_type: "bearer",
            expires_in: 900,
          });
        }
        if (url === "/some-endpoint") {
          if (firstAttempt) {
            // Only the very first call across both concurrent callers 401s;
            // subsequent (post-refresh) calls succeed. This models "token is
            // simply expired" rather than every call failing forever.
            firstAttempt = false;
            return jsonResponse({}, 401);
          }
          return jsonResponse({ ok: true });
        }
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    const [a, b] = await Promise.all([
      apiFetch("/some-endpoint"),
      apiFetch("/some-endpoint"),
    ]);

    expect(a).toEqual({ ok: true });
    expect(b).toEqual({ ok: true });
    expect(refreshCalls).toBe(1);
  });

  it("clears tokens and throws AuthRequiredError when refresh fails", async () => {
    setRefreshToken("stale-refresh-token");

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url === "/auth/refresh") return jsonResponse({}, 401);
        if (url === "/some-endpoint") return jsonResponse({}, 401);
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    await expect(apiFetch("/some-endpoint")).rejects.toBeInstanceOf(AuthRequiredError);
    expect(localStorage.getItem("redline.refresh_token")).toBeNull();
  });

  it("throws AuthRequiredError immediately when no refresh token is stored", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url === "/some-endpoint") return jsonResponse({}, 401);
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    await expect(apiFetch("/some-endpoint")).rejects.toBeInstanceOf(AuthRequiredError);
  });

  it("retries the original request with the newly refreshed token", async () => {
    setRefreshToken("stored-refresh-token");
    const seenAuthHeaders: (string | null)[] = [];

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url === "/auth/refresh") {
          return jsonResponse({
            access_token: "fresh-access-token",
            refresh_token: "rotated-refresh-token",
            token_type: "bearer",
            expires_in: 900,
          });
        }
        if (url === "/some-endpoint") {
          const auth = (init?.headers as Record<string, string> | undefined)?.Authorization ?? null;
          seenAuthHeaders.push(auth);
          if (auth === "Bearer fresh-access-token") return jsonResponse({ ok: true });
          return jsonResponse({}, 401);
        }
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    const result = await apiFetch("/some-endpoint");
    expect(result).toEqual({ ok: true });
    expect(seenAuthHeaders).toEqual([null, "Bearer fresh-access-token"]);
  });
});
