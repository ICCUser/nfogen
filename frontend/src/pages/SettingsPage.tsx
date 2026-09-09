import { useEffect, useState } from "react";
import { createAccount, deleteAccount, gapscanConfig, gapscanConfigWrite, listAccounts } from "../api/client";
import { getAuthStatus, getBaseUrl, login, logout, setBaseUrl } from "../api/settings";
import { ApiError } from "../api/types";
import type { GapscanConfig, GapscanConfigWrite } from "../api/types";
import { KeyValueEditor } from "../components/ListEditor";
import { useProfile } from "../ProfileContext";

export default function SettingsPage() {
  const [baseUrl, setBaseUrlState] = useState(getBaseUrl());
  const [baseUrlSaved, setBaseUrlSaved] = useState(false);

  // Configuration GLOBALE (Sonarr/Radarr/qBittorrent/TMDB/mise en scene/
  // mappings de chemins) : migree depuis LibraryPage (retour utilisateur,
  // 2026-09-07 -- independante du profil de tracker actif, pas sa place
  // sur la page Bibliotheque). Repliee par defaut, depliee automatiquement
  // si ni Sonarr ni Radarr ne sont configures (voir l'effet plus bas).
  const { profile } = useProfile();
  const [gConfig, setGConfig] = useState<GapscanConfig | null>(null);
  const [showGlobalConfigForm, setShowGlobalConfigForm] = useState(false);
  const [globalConfigSaving, setGlobalConfigSaving] = useState(false);
  const [globalConfigSaved, setGlobalConfigSaved] = useState(false);
  const [globalConfigError, setGlobalConfigError] = useState<string | null>(null);
  const [sonarrUrl, setSonarrUrl] = useState("");
  const [sonarrApiKey, setSonarrApiKey] = useState("");
  const [radarrUrl, setRadarrUrl] = useState("");
  const [radarrApiKey, setRadarrApiKey] = useState("");
  const [sonarrPathMappings, setSonarrPathMappings] = useState<Record<string, string>>({});
  const [radarrPathMappings, setRadarrPathMappings] = useState<Record<string, string>>({});
  const [stagingDir, setStagingDir] = useState("");
  const [qbittorrentUrl, setQbittorrentUrl] = useState("");
  const [qbittorrentUsername, setQbittorrentUsername] = useState("");
  const [qbittorrentPassword, setQbittorrentPassword] = useState("");
  const [qbittorrentVerifySsl, setQbittorrentVerifySsl] = useState(true);
  const [tmdbApiKey, setTmdbApiKey] = useState("");

  useEffect(() => {
    gapscanConfig(profile)
      .catch(() => null)
      .then((c) => {
        if (!c) return;
        setGConfig(c);
        setSonarrUrl(c.sonarr_url ?? "");
        setRadarrUrl(c.radarr_url ?? "");
        setSonarrPathMappings(c.sonarr_path_mappings);
        setRadarrPathMappings(c.radarr_path_mappings);
        setStagingDir(c.staging_dir ?? "");
        setQbittorrentUrl(c.qbittorrent_url ?? "");
        setQbittorrentVerifySsl(c.qbittorrent_verify_ssl ?? true);
        if (!c.sonarr_configured && !c.radarr_configured) setShowGlobalConfigForm(true);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile]);

  async function handleSaveGlobalConfig() {
    setGlobalConfigSaving(true);
    setGlobalConfigError(null);
    setGlobalConfigSaved(false);
    try {
      // Seuls les champs non vides sont envoyes : un champ cle laisse vide
      // ne doit pas effacer une valeur deja enregistree (PUT partiel cote
      // serveur, voir gapscan_config_store.write()).
      const fields: GapscanConfigWrite = {};
      if (sonarrUrl.trim()) fields.sonarr_url = sonarrUrl.trim();
      if (sonarrApiKey.trim()) fields.sonarr_api_key = sonarrApiKey.trim();
      if (radarrUrl.trim()) fields.radarr_url = radarrUrl.trim();
      if (radarrApiKey.trim()) fields.radarr_api_key = radarrApiKey.trim();
      if (stagingDir.trim()) fields.staging_dir = stagingDir.trim();
      if (qbittorrentUrl.trim()) fields.qbittorrent_url = qbittorrentUrl.trim();
      if (qbittorrentUsername.trim()) fields.qbittorrent_username = qbittorrentUsername.trim();
      if (qbittorrentPassword.trim()) fields.qbittorrent_password = qbittorrentPassword.trim();
      if (tmdbApiKey.trim()) fields.tmdb_api_key = tmdbApiKey.trim();
      // Contrairement aux champs texte ci-dessus, une case a cocher
      // represente toujours une valeur explicite (pas d'etat "vide") --
      // toujours envoyee.
      fields.qbittorrent_verify_ssl = qbittorrentVerifySsl;
      // Contrairement aux cles/URLs ci-dessus, un dictionnaire vide est une
      // valeur explicite valide ("aucun mapping") : toujours envoye.
      fields.sonarr_path_mappings = sonarrPathMappings;
      fields.radarr_path_mappings = radarrPathMappings;

      const updated = await gapscanConfigWrite(fields, profile);
      setGConfig(updated);
      setSonarrApiKey("");
      setRadarrApiKey("");
      setQbittorrentPassword("");
      setTmdbApiKey("");
      setGlobalConfigSaved(true);
      setTimeout(() => setGlobalConfigSaved(false), 2000);
    } catch (e) {
      setGlobalConfigError(e instanceof ApiError ? e.message : "Enregistrement impossible.");
    } finally {
      setGlobalConfigSaving(false);
    }
  }

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
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <div className="space-y-6">
      <div className="max-w-md space-y-4">
        <h1 className="font-display text-xl font-semibold text-ink">Réglages de connexion</h1>
        <label className="block text-sm font-medium text-ink-dim">
          URL de base de l'API
          <input
            className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
            value={baseUrl}
            onChange={(e) => setBaseUrlState(e.target.value)}
            placeholder="(même origine, vide par défaut)"
          />
        </label>
        <button
          type="button"
          onClick={saveBaseUrl}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90"
        >
          Enregistrer
        </button>
        {baseUrlSaved && <span className="ml-3 text-sm text-good">Enregistré.</span>}
      </div>

      <div className="max-w-md space-y-3 border-t border-line pt-4">
        <h2 className="font-display text-lg font-semibold text-ink">Authentification</h2>

        {!authRequired && (
          <p className="text-sm text-ink-dim">
            Cette API n'a pas été démarrée avec{" "}
            <code className="rounded bg-surface-2 px-1 font-mono">NFOGEN_API_TOKEN</code> ni{" "}
            <code className="rounded bg-surface-2 px-1 font-mono">NFOGEN_ACCOUNTS_FILE</code> : aucune
            connexion n'est nécessaire.
          </p>
        )}

        {authRequired && authenticated && (
          <div className="space-y-2">
            <p className="text-sm text-good">Connecté.</p>
            <button
              type="button"
              disabled={busy}
              onClick={handleLogout}
              className="rounded-md border border-line-strong px-4 py-2 text-sm font-medium text-ink hover:bg-surface-2 disabled:opacity-50"
            >
              Se déconnecter
            </button>
          </div>
        )}

        {!authenticated && accountsBootstrapAvailable && (
          <div className="space-y-2 rounded-md border border-warn bg-warn-bg p-3">
            <p className="text-sm text-warn">
              Aucun compte administrateur n'existe encore : créez le premier (vous serez
              automatiquement connecté).
            </p>
            <label className="block text-sm font-medium text-ink-dim">
              Identifiant
              <input
                className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
                value={newAccountUsername}
                onChange={(e) => setNewAccountUsername(e.target.value)}
              />
            </label>
            <label className="block text-sm font-medium text-ink-dim">
              Mot de passe
              <input
                className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
                type="password"
                value={newAccountPassword}
                onChange={(e) => setNewAccountPassword(e.target.value)}
              />
            </label>
            <button
              type="button"
              disabled={busy || !newAccountUsername.trim() || !newAccountPassword}
              onClick={handleBootstrap}
              className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90 disabled:opacity-50"
            >
              Créer ce compte et se connecter
            </button>
          </div>
        )}

        {!authenticated && !accountsBootstrapAvailable && accountsLoginEnabled && (
          <div className="space-y-2">
            <label className="block text-sm font-medium text-ink-dim">
              Identifiant
              <input
                className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
            <label className="block text-sm font-medium text-ink-dim">
              Mot de passe
              <input
                className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
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
              className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90 disabled:opacity-50"
            >
              Se connecter
            </button>
          </div>
        )}

        {!authenticated && !accountsBootstrapAvailable && tokenLoginEnabled && (
          <div className="space-y-2">
            {accountsLoginEnabled && (
              <p className="text-sm text-ink-faint">Ou avec le token API partagé :</p>
            )}
            <label className="block text-sm font-medium text-ink-dim">
              Token API
              <input
                className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
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
              className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90 disabled:opacity-50"
            >
              Se connecter
            </button>
          </div>
        )}

        {error && <p className="text-sm text-crit">{error}</p>}
      </div>
      </div>

      <div className="space-y-6">
      {authenticated && accountsLoginEnabled && (
        <div className="max-w-md space-y-3 border-t border-line pt-4 lg:border-t-0 lg:pt-0">
          <h2 className="font-display text-lg font-semibold text-ink">Comptes administrateurs</h2>
          <p className="text-sm text-ink-dim">
            Tous les comptes ont les mêmes droits — l'intérêt est de pouvoir révoquer un accès
            précis sans changer le secret des autres.
          </p>

          {accountsError && <p className="text-sm text-crit">{accountsError}</p>}

          {accountNames && (
            <ul className="divide-y divide-line rounded-md border border-line bg-surface">
              {accountNames.map((name) => (
                <li key={name} className="flex items-center justify-between px-3 py-2 text-sm">
                  <span className="font-mono text-ink">{name}</span>
                  <button
                    type="button"
                    onClick={() => handleDeleteAccount(name)}
                    className="text-sm text-crit underline hover:opacity-80"
                  >
                    Supprimer
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="flex items-end gap-2">
            <label className="block text-sm font-medium text-ink-dim">
              Identifiant
              <input
                className="mt-1 rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
                value={newAccountUsername}
                onChange={(e) => setNewAccountUsername(e.target.value)}
              />
            </label>
            <label className="block text-sm font-medium text-ink-dim">
              Mot de passe
              <input
                className="mt-1 rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
                type="password"
                value={newAccountPassword}
                onChange={(e) => setNewAccountPassword(e.target.value)}
              />
            </label>
            <button
              type="button"
              disabled={!newAccountUsername.trim() || !newAccountPassword}
              onClick={handleAddAccount}
              className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90 disabled:opacity-50"
            >
              Ajouter
            </button>
          </div>
        </div>
      )}

      <div className="space-y-3 border-t border-line pt-4">
        <div className="rounded-md border border-line bg-surface">
          <button
            type="button"
            onClick={() => setShowGlobalConfigForm((v) => !v)}
            className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium text-ink"
          >
            Configuration globale (Sonarr, Radarr, qBittorrent, TMDB)
            <span className="text-ink-faint">{showGlobalConfigForm ? "▲" : "▼"}</span>
          </button>
          {showGlobalConfigForm && (
            <div className="space-y-3 border-t border-line p-4">
              <p className="text-xs text-ink-faint">
                Commune à tous les profils — indépendante du profil de tracker actif. Enregistré
                côté serveur ({" "}
                <code className="rounded bg-surface-2 px-1 font-mono">NFOGEN_GAPSCAN_CONFIG_FILE</code>{" "}
                requis). Un champ « clé »/« mot de passe » laissé vide ne modifie pas la valeur
                déjà enregistrée.
              </p>

              <div className="grid grid-cols-2 gap-3">
                <label className="block text-sm font-medium text-ink-dim">
                  URL Sonarr
                  <input
                    className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                    placeholder="http://sonarr.local:8989"
                    value={sonarrUrl}
                    onChange={(e) => setSonarrUrl(e.target.value)}
                  />
                </label>
                <label className="block text-sm font-medium text-ink-dim">
                  Clé API Sonarr
                  <input
                    className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                    type="password"
                    placeholder={gConfig?.sonarr_configured ? "•••• (enregistrée)" : ""}
                    value={sonarrApiKey}
                    onChange={(e) => setSonarrApiKey(e.target.value)}
                  />
                </label>
                <label className="block text-sm font-medium text-ink-dim">
                  URL Radarr
                  <input
                    className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                    placeholder="http://radarr.local:7878"
                    value={radarrUrl}
                    onChange={(e) => setRadarrUrl(e.target.value)}
                  />
                </label>
                <label className="block text-sm font-medium text-ink-dim">
                  Clé API Radarr
                  <input
                    className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                    type="password"
                    placeholder={gConfig?.radarr_configured ? "•••• (enregistrée)" : ""}
                    value={radarrApiKey}
                    onChange={(e) => setRadarrApiKey(e.target.value)}
                  />
                </label>
                <label className="block text-sm font-medium text-ink-dim">
                  Dossier de mise en scène
                  <input
                    className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                    placeholder="/data/staging"
                    value={stagingDir}
                    onChange={(e) => setStagingDir(e.target.value)}
                  />
                </label>
                <label className="block text-sm font-medium text-ink-dim">
                  URL qBittorrent
                  <input
                    className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                    placeholder="http://qbittorrent.local:8080"
                    value={qbittorrentUrl}
                    onChange={(e) => setQbittorrentUrl(e.target.value)}
                  />
                </label>
                <label className="block text-sm font-medium text-ink-dim">
                  Utilisateur qBittorrent
                  <input
                    className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                    value={qbittorrentUsername}
                    onChange={(e) => setQbittorrentUsername(e.target.value)}
                  />
                </label>
                <label className="block text-sm font-medium text-ink-dim">
                  Mot de passe qBittorrent
                  <input
                    className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                    type="password"
                    placeholder={gConfig?.qbittorrent_configured ? "•••• (enregistré)" : ""}
                    value={qbittorrentPassword}
                    onChange={(e) => setQbittorrentPassword(e.target.value)}
                  />
                </label>
                <label className="flex items-center gap-2 text-sm font-medium text-ink-dim">
                  <input
                    type="checkbox"
                    checked={qbittorrentVerifySsl}
                    onChange={(e) => setQbittorrentVerifySsl(e.target.checked)}
                  />
                  Vérifier le certificat SSL de qBittorrent
                </label>
                {!qbittorrentVerifySsl && (
                  <p className="text-xs text-ink-faint">
                    Désactivé : utile si le WebUI qBittorrent utilise un certificat auto-signé
                    (courant en HTTPS local) — la connexion reste chiffrée, seule la vérification
                    du certificat est ignorée.
                  </p>
                )}
                <label className="block text-sm font-medium text-ink-dim">
                  Clé API TMDB
                  <input
                    className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                    type="password"
                    placeholder={gConfig?.tmdb_configured ? "•••• (enregistrée)" : ""}
                    value={tmdbApiKey}
                    onChange={(e) => setTmdbApiKey(e.target.value)}
                  />
                </label>
              </div>

              <div className="space-y-2">
                <p className="text-sm font-medium text-ink-dim">
                  Mapping de chemins Sonarr (si nfogen ne voit pas les mêmes chemins que Sonarr)
                </p>
                <KeyValueEditor
                  value={sonarrPathMappings}
                  onChange={setSonarrPathMappings}
                  keyPlaceholder="Chemin distant (Sonarr)"
                  valuePlaceholder="Chemin local (nfogen)"
                />
              </div>
              <div className="space-y-2">
                <p className="text-sm font-medium text-ink-dim">
                  Mapping de chemins Radarr (si nfogen ne voit pas les mêmes chemins que Radarr)
                </p>
                <KeyValueEditor
                  value={radarrPathMappings}
                  onChange={setRadarrPathMappings}
                  keyPlaceholder="Chemin distant (Radarr)"
                  valuePlaceholder="Chemin local (nfogen)"
                />
              </div>

              {globalConfigError && <p className="text-sm text-crit">{globalConfigError}</p>}

              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={handleSaveGlobalConfig}
                  disabled={globalConfigSaving}
                  className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90 disabled:opacity-50"
                >
                  {globalConfigSaving ? "Enregistrement…" : "Enregistrer"}
                </button>
                {globalConfigSaved && <span className="text-sm text-good">Enregistré.</span>}
              </div>
            </div>
          )}
        </div>
      </div>
      </div>
    </div>
  );
}
