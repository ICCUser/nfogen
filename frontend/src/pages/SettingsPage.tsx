import { useEffect, useState } from "react";
import { getAuthStatus, getBaseUrl, login, logout, setBaseUrl } from "../api/settings";

export default function SettingsPage() {
  const [baseUrl, setBaseUrlState] = useState(getBaseUrl());
  const [baseUrlSaved, setBaseUrlSaved] = useState(false);
  const [token, setToken] = useState("");
  const [authRequired, setAuthRequired] = useState(false);
  const [authenticated, setAuthenticated] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function refreshAuthStatus() {
    getAuthStatus()
      .then((status) => {
        setAuthRequired(status.authRequired);
        setAuthenticated(status.authenticated);
      })
      .catch(() => {
        // API injoignable : ne bloque pas l'affichage de la page, le reste
        // de l'interface remontera l'erreur reseau au bon endroit.
      });
  }

  useEffect(refreshAuthStatus, []);

  function saveBaseUrl() {
    setBaseUrl(baseUrl.trim());
    setBaseUrlSaved(true);
    setTimeout(() => setBaseUrlSaved(false), 1500);
    refreshAuthStatus();
  }

  async function handleLogin() {
    setBusy(true);
    setError(null);
    try {
      await login(token.trim());
      setToken("");
      refreshAuthStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur de connexion.");
    } finally {
      setBusy(false);
    }
  }

  async function handleLogout() {
    setBusy(true);
    try {
      await logout();
      refreshAuthStatus();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-lg space-y-6">
      <div className="space-y-4">
        <h1 className="text-xl font-semibold text-slate-900">Réglages de connexion</h1>
        <label className="block text-sm font-medium text-slate-700">
          URL de base de l'API
          <input
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            value={baseUrl}
            onChange={(e) => setBaseUrlState(e.target.value)}
            placeholder="/api"
          />
        </label>
        <button
          type="button"
          onClick={saveBaseUrl}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
        >
          Enregistrer
        </button>
        {baseUrlSaved && <span className="ml-3 text-sm text-emerald-600">Enregistré.</span>}
      </div>

      <div className="space-y-3 border-t border-slate-200 pt-4">
        <h2 className="text-lg font-semibold text-slate-900">Authentification</h2>
        {!authRequired && (
          <p className="text-sm text-slate-600">
            Cette API n'a pas été démarrée avec{" "}
            <code className="rounded bg-slate-100 px-1">NFOGEN_API_TOKEN</code> : aucune
            connexion n'est nécessaire.
          </p>
        )}
        {authRequired && authenticated && (
          <div className="space-y-2">
            <p className="text-sm text-emerald-600">Connecté.</p>
            <button
              type="button"
              disabled={busy}
              onClick={handleLogout}
              className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50"
            >
              Se déconnecter
            </button>
          </div>
        )}
        {authRequired && !authenticated && (
          <div className="space-y-2">
            <p className="text-sm text-slate-600">
              Le serveur posera un cookie de session (httpOnly, jamais lisible en
              JavaScript) — le token lui-même n'est jamais conservé par le navigateur.
            </p>
            <label className="block text-sm font-medium text-slate-700">
              Token API
              <input
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleLogin()}
              />
            </label>
            <button
              type="button"
              disabled={busy || !token.trim()}
              onClick={handleLogin}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              Se connecter
            </button>
            {error && <p className="text-sm text-red-600">{error}</p>}
          </div>
        )}
      </div>
    </div>
  );
}
