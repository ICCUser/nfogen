import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getAuthStatus, getBaseUrl, login, logout, setBaseUrl } from "./settings";

function fakeResponse(body: unknown, init: { ok?: boolean } = {}): Response {
  return {
    ok: init.ok ?? true,
    json: async () => body,
  } as Response;
}

describe("getBaseUrl / setBaseUrl", () => {
  beforeEach(() => localStorage.clear());

  it("defaults to /api when nothing stored", () => {
    expect(getBaseUrl()).toBe("/api");
  });

  it("round-trips a value through localStorage", () => {
    setBaseUrl("https://example.test/api");
    expect(getBaseUrl()).toBe("https://example.test/api");
  });
});

describe("getAuthStatus", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => vi.unstubAllGlobals());

  it("maps the snake_case response to camelCase", async () => {
    vi.mocked(fetch).mockResolvedValue(
      fakeResponse({
        auth_required: true,
        authenticated: false,
        token_login_enabled: true,
        accounts_login_enabled: false,
        accounts_bootstrap_available: true,
      }),
    );

    const status = await getAuthStatus();

    expect(status).toEqual({
      authRequired: true,
      authenticated: false,
      tokenLoginEnabled: true,
      accountsLoginEnabled: false,
      accountsBootstrapAvailable: true,
    });
    expect(fetch).toHaveBeenCalledWith("/api/auth/status", { credentials: "include" });
  });
});

describe("login", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => vi.unstubAllGlobals());

  it("posts credentials with credentials: include, no error on success", async () => {
    vi.mocked(fetch).mockResolvedValue(fakeResponse({ status: "ok" }));

    await login({ token: "secret" });

    expect(fetch).toHaveBeenCalledWith(
      "/api/login",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: "secret" }),
      }),
    );
  });

  it("throws the server detail message on failure", async () => {
    vi.mocked(fetch).mockResolvedValue(fakeResponse({ detail: "Token API invalide." }, { ok: false }));

    await expect(login({ token: "wrong" })).rejects.toThrow("Token API invalide.");
  });

  it("falls back to a generic message when the error body isn't JSON", async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      json: async () => {
        throw new Error("not json");
      },
    } as unknown as Response);

    await expect(login({ username: "x", password: "y" })).rejects.toThrow("Connexion refusee.");
  });
});

describe("logout", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse({}))));
  afterEach(() => vi.unstubAllGlobals());

  it("posts to /logout with credentials included", async () => {
    await logout();
    expect(fetch).toHaveBeenCalledWith("/api/logout", { method: "POST", credentials: "include" });
  });
});
