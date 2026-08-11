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

  it("defaults to /api in dev (import.meta.env.DEV, matches vite dev's proxy)", () => {
    expect(getBaseUrl()).toBe("/api");
  });

  it("round-trips a value through localStorage", () => {
    setBaseUrl("https://example.test/api");
    expect(getBaseUrl()).toBe("https://example.test/api");
  });

  it("an explicitly saved empty string is honored, not silently replaced by the default", () => {
    // Cas reel : un utilisateur qui avait "/api" enregistre de longue date
    // (ancien defaut) doit pouvoir revenir manuellement a "meme origine" en
    // vidant le champ dans Reglages -- une chaine vide n'est PAS "rien
    // n'est enregistre" (`||` aurait retabli DEFAULT_BASE_URL a tort ; `??`
    // ne se declenche que sur `null`, ce que retourne getItem quand la cle
    // est vraiment absente).
    setBaseUrl("/api");
    expect(getBaseUrl()).toBe("/api");
    setBaseUrl("");
    expect(getBaseUrl()).toBe("");
  });
});

describe("DEFAULT_BASE_URL in a production build", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("defaults to same-origin (no /api prefix), matching nfogen/api.py's unprefixed routes", async () => {
    // nfogen/api.py monte /profiles, /generate... SANS prefixe /api : servi
    // en un seul processus (NFOGEN_FRONTEND_DIST, scripts/install.sh), un
    // frontend qui garderait le prefixe /api de dev tomberait sur le SPA
    // fallback (index.html) au lieu du JSON attendu -- cause exacte d'un
    // crash de rendu observe en production (ProfilesListPage, "categories.join
    // is not a function") avant ce correctif.
    vi.stubEnv("DEV", false);
    vi.resetModules();
    const prodSettings = await import("./settings");
    localStorage.clear();
    expect(prodSettings.getBaseUrl()).toBe("");
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
