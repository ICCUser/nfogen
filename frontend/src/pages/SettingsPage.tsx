import { useEffect, useState } from "react";
import { createAccount, deleteAccount, listAccounts } from "../api/client";
import { getAuthStatus, getBaseUrl, login, logout, setBaseUrl } from "../api/settings";
import { ApiError } from "../api/types";

export default function SettingsPage() {
  const [baseUrl, setBaseUrlState] = useState(getBaseUrl());
  const [baseUrlSaved, setBaseUrlSaved] = useState(false);

  const [tokenLoginEnabled, setTokenLoginEnabled] = useState(false);
  const [accountsLoginEnabled, setAccountsLoginEnabled] = useState(false);
  const [accountsBootstrapAvailable, setAccountsBootstrapAvailable] = useState(false);
  const [authRequired, setAuthRequired] = useState(false);
  const [authenticated, setAuthenticated] = useState(true);

  const [token, setToken] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [accountNames, setAccountNames] = useState<string[] | null>(null);
  const [accountsError, setAccountsError] = useState<string | null>(null);
  const [newAccountUsername, setNewAccountUsername] = useState("");
  const [newAccountPassword, setNewAccountPassword] = useState("");

  function refreshAuthStatus() {
    getAuthStatus()
      .then((status) => {
        setAuthRequired(status.authRequired);
        setAuthenticated(status.authenticated);
        setTokenLoginEnabled(status.tokenLoginEnabled);
        setAccountsLoginEnabled(status.accountsLoginEnabled);
        setAccountsBootstrapAvailable(status.accountsBootstrapAvailable);
      })
      .catch(() => {
        // API injoignable : ne bloque pas l'affichage de la page, le reste
        // de l'interface remontera l'erreur reseau au bon endroit.
      });
  }

  function refreshAccounts() {
    setAccountsError(null);
    listAccounts()
      .then(setAccountNames)
      .catch((e) => {
        setAccountNames(null);
        setAccountsError(e instanceof ApiError ? e.message : "Comptes indisponibles.");
      });
  }

  useEffect(refreshAuthStatus, []);
  useEffect(() => {
    if (authenticated && accountsLoginEnabled) refreshAccounts();
  }, [authenticated, accountsLoginEnabled]);

  function saveBaseUrl() {
    setBaseUrl(baseUrl.trim());
    setBaseUrlSaved(true);
    setTimeout(() => setBaseUrlSaved(false), 1500);
    refreshAuthStatus();
  }

  async function handleTokenLogin() {
    setBusy(true);
    setError(null);
    try {
      await login({ token: token.trim() });
      setToken("");
      refreshAuthStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur de connexion.");
    } finally {
      setBusy(false);
    }
  }

  async function handleAccountLogin() {
    setBusy(true);
    setError(null);
    try {
      await login({ username: username.trim(), password });
      setPassword("");
      refreshAuthStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur de connexion.");
    } finally {
      setBusy(false);
    }
  }

  async function handleBootstrap() {
    setBusy(true);
    setError(null);
    try {
      await createAccount(newAccountUsername.trim(), newAccountPassword);
      await login({ username: newAccountUsername.trim(), password: newAccountPassword });
      setNewAccountUsername("");
      setNewAccountPassword("");
      refreshAuthStatus();
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : "Erreur inattendue.");
    } finally {
      setBusy(false);
    }
  }

  async function handleAddAccount() {
    setAccountsError(null);
    try {
      await createAccount(newAccountUsername.trim(), newAccountPassword);
      setNewAccountUsername("");
      setNewAccountPassword("");
      refreshAccounts();
    } catch (e) {
      setAccountsError(e instanceof ApiError ? e.message : "Erreur inattendue.");
    }
  }

  async function handleDeleteAccount(name: string) {
    if (!confirm(`Supprimer le compte '${name}' ? Ses sessions actives seront immediatement revoquees.`)) return;
    setAccountsError(null);
    try {
      await deleteAccount(name);
      refreshAccounts();
    } catch (e) {
      setAccountsError(e instanceof ApiError ? e.message : "Erreur inattendue.");
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
            <code className="rounded bg-slate-100 px-1">NFOGEN_API_TOKEN</code> ni{" "}
            <code className="rounded bg-slate-100 px-1">NFOGEN_ACCOUNTS_FILE</code> : aucune
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

        {!authenticated && accountsBootstrapAvailable && (
          <div className="space-y-2 rounded-md border border-amber-200 bg-amber-50 p-3">
            <p className="text-sm text-amber-800">
              Aucun compte administrateur n'existe encore : créez le premier (vous serez
              automatiquement connecté).
            </p>
            <label className="block text-sm font-medium text-slate-700">
              Identifiant
              <input
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                value={newAccountUsername}
                onChange={(e) => setNewAccountUsername(e.target.value)}
              />
            </label>
            <label className="block text-sm font-medium text-slate-700">
              Mot de passe
              <input
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                type="password"
                value={newAccountPassword}
                onChange={(e) => setNewAccountPassword(e.target.value)}
              />
            </label>
            <button
              type="button"
              disabled={busy || !newAccountUsername.trim() || !newAccountPassword}
              onClick={handleBootstrap}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              Créer ce compte et se connecter
            </button>
          </div>
        )}

        {!authenticated && !accountsBootstrapAvailable && accountsLoginEnabled && (
          <div className="space-y-2">
            <label className="block text-sm font-medium text-slate-700">
              Identifiant
              <input
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
            <label className="block text-sm font-medium text-slate-700">
              Mot de passe
              <input
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleAccountLogin()}
              />
            </label>
            <button
              type="button"
              disabled={busy || !username.trim() || !password}
              onClick={handleAccountLogin}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              Se connecter
            </button>
          </div>
        )}

        {!authenticated && !accountsBootstrapAvailable && tokenLoginEnabled && (
          <div className="space-y-2">
            {accountsLoginEnabled && (
              <p className="text-sm text-slate-500">Ou avec le token API partagé :</p>
            )}
            <label className="block text-sm font-medium text-slate-700">
              Token API
              <input
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleTokenLogin()}
              />
            </label>
            <button
              type="button"
              disabled={busy || !token.trim()}
              onClick={handleTokenLogin}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              Se connecter
            </button>
          </div>
        )}

        {error && <p className="text-sm text-red-600">{error}</p>}
      </div>

      {authenticated && accountsLoginEnabled && (
        <div className="space-y-3 border-t border-slate-200 pt-4">
          <h2 className="text-lg font-semibold text-slate-900">Comptes administrateurs</h2>
          <p className="text-sm text-slate-600">
            Tous les comptes ont les mêmes droits — l'intérêt est de pouvoir révoquer un accès
            précis sans changer le secret des autres.
          </p>

          {accountsError && <p className="text-sm text-red-600">{accountsError}</p>}

          {accountNames && (
            <ul className="divide-y divide-slate-200 rounded-md border border-slate-200 bg-white">
              {accountNames.map((name) => (
                <li key={name} className="flex items-center justify-between px-3 py-2 text-sm">
                  {name}
                  <button
                    type="button"
                    onClick={() => handleDeleteAccount(name)}
                    className="text-sm text-red-600 underline hover:text-red-700"
                  >
                    Supprimer
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="flex items-end gap-2">
            <label className="block text-sm font-medium text-slate-700">
              Identifiant
              <input
                className="mt-1 rounded-md border border-slate-300 px-3 py-2 text-sm"
                value={newAccountUsername}
                onChange={(e) => setNewAccountUsername(e.target.value)}
              />
            </label>
            <label className="block text-sm font-medium text-slate-700">
              Mot de passe
              <input
                className="mt-1 rounded-md border border-slate-300 px-3 py-2 text-sm"
                type="password"
                value={newAccountPassword}
                onChange={(e) => setNewAccountPassword(e.target.value)}
              />
            </label>
            <button
              type="button"
              disabled={!newAccountUsername.trim() || !newAccountPassword}
              onClick={handleAddAccount}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              Ajouter
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
