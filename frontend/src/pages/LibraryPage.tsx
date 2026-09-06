import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import ActiveTransfersTray from "../components/ActiveTransfersTray";
import { KeyValueEditor } from "../components/ListEditor";
import UploadPrepPanel from "../components/UploadPrepPanel";
import {
  clearGapscanLog,
  downloadBlob,
  gapscanConfig,
  gapscanConfigWrite,
  gapscanExportCsv,
  gapscanRun,
  gapscanStatus,
  libraryResults,
} from "../api/client";
import { ApiError } from "../api/types";
import type { GapscanConfig, GapscanConfigWrite, GapscanStatus, GapStatus, LibraryItem } from "../api/types";
import { useProfile } from "../ProfileContext";

/** Libelles de statut : parametres par le nom du tracker actif
 * (`trackerName`, voir ProfileContext.displayName) au lieu d'un "C411"
 * en dur. `null` (jamais scanne) -> "Non verifie". */
function statusLabel(status: GapStatus | null, trackerName: string): string {
  if (status === null) return "Non vérifié";
  const labels: Record<GapStatus, string> = {
    absent: `Absent de ${trackerName}`,
    quality_gap: "Qualité supérieure disponible",
    language_gap: `Langue manquante sur ${trackerName}`,
    covered: "Déjà couvert",
    error: `Non vérifié (erreur ${trackerName})`,
  };
  return labels[status];
}

const STATUS_BADGE_CLASS: Record<GapStatus, string> = {
  absent: "bg-info-bg text-info",
  quality_gap: "bg-warn-bg text-warn",
  language_gap: "bg-warn-bg text-warn",
  covered: "bg-surface-2 text-ink-faint",
  error: "bg-crit-bg text-crit",
};
const NOT_VERIFIED_BADGE_CLASS = "bg-surface-2 text-ink-faint";

function qualitySummary(q: LibraryItem["local_quality"]): string {
  const parts = [
    q.resolution ? `${q.resolution}p` : null,
    q.source,
    q.languages.length > 0 ? q.languages.join("+") : null,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : "—";
}

const PAGE_SIZE = 50;

/** Page "Bibliothèque" (AUTOMATION.md, sous-projet 8) : inventaire brut
 * Radarr/Sonarr, ZERO appel tracker par defaut, annote du statut du
 * DERNIER scan connu (bulk ou cible) des qu'il existe. Fusionne l'ancienne
 * page "Scan {tracker}" (retour utilisateur, 2026-09-06 : les deux pages
 * faisaient doublon -- "je trouve qu'elle sert pas en fait") : un seul
 * tableau, une seule configuration, un seul mecanisme de scan (bulk ou
 * restreint a la selection). */
export default function LibraryPage() {
  const { profile, displayName: trackerDisplayName } = useProfile();
  const STATUS_FILTERS: { value: GapStatus | "not_verified" | ""; label: string }[] = [
    { value: "", label: "Tous les statuts" },
    { value: "not_verified", label: "Non vérifié" },
    { value: "absent", label: statusLabel("absent", trackerDisplayName) },
    { value: "quality_gap", label: statusLabel("quality_gap", trackerDisplayName) },
    { value: "language_gap", label: statusLabel("language_gap", trackerDisplayName) },
    { value: "covered", label: statusLabel("covered", trackerDisplayName) },
    { value: "error", label: statusLabel("error", trackerDisplayName) },
  ];

  const [config, setConfig] = useState<GapscanConfig | null>(null);
  const [status, setStatus] = useState<GapscanStatus | null>(null);
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [mediaType, setMediaType] = useState<"" | "movie" | "series">("");
  const [genre, setGenre] = useState("");
  const [trackerGenre, setTrackerGenre] = useState<"" | "anime" | "documentaire">("");
  const [statusFilter, setStatusFilter] = useState<GapStatus | "not_verified" | "">("");
  const [addedSinceDays, setAddedSinceDays] = useState("");
  const [processed, setProcessed] = useState<"" | "true" | "false">("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [starting, setStarting] = useState(false);
  const [activeUpload, setActiveUpload] = useState<{
    title: string;
    localPaths: string[];
    mediaType: "movie" | "series";
    radarrMovieId: number | null;
    sonarrSeriesId: number | null;
    tmdbId: number | null;
    tvdbId: number | null;
    genre: "anime" | "documentaire" | null;
    seasonNumber: number | null;
  } | null>(null);

  // Scan rapide (mode incremental) : coche par defaut des qu'un scan
  // precedent existe -- l'utilisateur peut decocher pour forcer un scan
  // complet (voir GAPSCAN.md, "Persistance des resultats + scan
  // incremental").
  const [incremental, setIncremental] = useState(true);
  // Scan par categorie (retour utilisateur, 2026-08-27) : scanner Radarr et
  // Sonarr separement, pour repartir la charge sur plusieurs sessions
  // (limite C411 confirmee : 15 requetes/min).
  const [only, setOnly] = useState<"" | "movies" | "series">("");
  const pollRef = useRef<number | null>(null);

  // Formulaire de configuration (Sonarr/Radarr/tracker) : replie par
  // defaut, deplie automatiquement une fois qu'on sait qu'il manque
  // quelque chose (voir l'effet plus bas, une fois `config` charge).
  const [showConfigForm, setShowConfigForm] = useState(false);
  const [configSaving, setConfigSaving] = useState(false);
  const [configSaved, setConfigSaved] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);
  const [sonarrUrl, setSonarrUrl] = useState("");
  const [sonarrApiKey, setSonarrApiKey] = useState("");
  const [radarrUrl, setRadarrUrl] = useState("");
  const [radarrApiKey, setRadarrApiKey] = useState("");
  const [trackerApiKey, setTrackerApiKey] = useState("");
  const [trackerBaseUrl, setTrackerBaseUrl] = useState("");
  const [sonarrPathMappings, setSonarrPathMappings] = useState<Record<string, string>>({});
  const [radarrPathMappings, setRadarrPathMappings] = useState<Record<string, string>>({});
  const [trackerAnnounceUrl, setTrackerAnnounceUrl] = useState("");
  const [stagingDir, setStagingDir] = useState("");
  const [qbittorrentUrl, setQbittorrentUrl] = useState("");
  const [qbittorrentUsername, setQbittorrentUsername] = useState("");
  const [qbittorrentPassword, setQbittorrentPassword] = useState("");

  useEffect(() => {
    gapscanConfig(profile)
      .catch(() => null)
      .then((c) => {
        if (!c) return;
        setConfig(c);
        setSonarrUrl(c.sonarr_url ?? "");
        setRadarrUrl(c.radarr_url ?? "");
        setTrackerBaseUrl(c.tracker_base_url ?? "");
        setSonarrPathMappings(c.sonarr_path_mappings);
        setRadarrPathMappings(c.radarr_path_mappings);
        setStagingDir(c.staging_dir ?? "");
        setQbittorrentUrl(c.qbittorrent_url ?? "");
        if (!c.tracker_configured || (!c.sonarr_configured && !c.radarr_configured)) {
          setShowConfigForm(true);
        }
      });
    refreshStatus();
    return () => stopPolling();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, mediaType, genre, trackerGenre, statusFilter, addedSinceDays, processed, page, profile]);

  function resetPageAnd<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v);
      setPage(1);
    };
  }

  function stopPolling() {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function startPolling() {
    stopPolling();
    pollRef.current = window.setInterval(async () => {
      const s = await refreshStatus();
      if (s && s.state !== "running") {
        stopPolling();
        load();
      }
    }, 1500);
  }

  async function refreshStatus(): Promise<GapscanStatus | null> {
    try {
      const s = await gapscanStatus();
      setStatus(s);
      if (s.state === "running" && pollRef.current === null) startPolling();
      return s;
    } catch {
      return null;
    }
  }

  async function load() {
    try {
      const res = await libraryResults({
        q: q || undefined,
        mediaType: mediaType || undefined,
        genre: genre || undefined,
        trackerGenre: trackerGenre || undefined,
        status: statusFilter || undefined,
        addedSinceDays: addedSinceDays ? Number(addedSinceDays) : undefined,
        processed: processed === "" ? undefined : processed === "true",
        page,
        pageSize: PAGE_SIZE,
        profile,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch (e) {
      setItems(null);
      setTotal(0);
      setError(e instanceof ApiError ? e.message : "Bibliothèque indisponible.");
    }
  }

  function toggleOne(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function selectAllFiltered() {
    if (!items) return;
    setSelected(new Set(items.map((i) => i.key)));
  }

  function clearSelection() {
    setSelected(new Set());
  }

  async function handleRun() {
    setStarting(true);
    setError(null);
    try {
      await gapscanRun(hasPreviousScan && incremental, only || undefined, profile);
      // refreshStatus() demarre elle-meme le polling si l'etat est
      // "running" -- pas d'appel a startPolling() ici : un scan deja
      // termine au premier appel ne doit pas en declencher un inutilement.
      const s = await refreshStatus();
      if (s && s.state !== "running") load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Impossible de lancer le scan.");
    } finally {
      setStarting(false);
    }
  }

  async function handleVerifySelection() {
    if (selected.size === 0) return;
    setStarting(true);
    setError(null);
    try {
      await gapscanRun(false, undefined, profile, Array.from(selected));
      clearSelection();
      const s = await refreshStatus();
      if (s && s.state !== "running") load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Impossible de lancer le scan.");
    } finally {
      setStarting(false);
    }
  }

  async function handleSaveConfig() {
    setConfigSaving(true);
    setConfigError(null);
    setConfigSaved(false);
    try {
      // Seuls les champs non vides sont envoyes : un champ cle laisse vide
      // ne doit pas effacer une valeur deja enregistree (PUT partiel cote
      // serveur, voir gapscan_config_store.write()).
      const fields: GapscanConfigWrite = {};
      if (sonarrUrl.trim()) fields.sonarr_url = sonarrUrl.trim();
      if (sonarrApiKey.trim()) fields.sonarr_api_key = sonarrApiKey.trim();
      if (radarrUrl.trim()) fields.radarr_url = radarrUrl.trim();
      if (radarrApiKey.trim()) fields.radarr_api_key = radarrApiKey.trim();
      if (trackerApiKey.trim()) fields.tracker_api_key = trackerApiKey.trim();
      if (trackerBaseUrl.trim()) fields.tracker_base_url = trackerBaseUrl.trim();
      if (trackerAnnounceUrl.trim()) fields.tracker_announce_url = trackerAnnounceUrl.trim();
      if (stagingDir.trim()) fields.staging_dir = stagingDir.trim();
      if (qbittorrentUrl.trim()) fields.qbittorrent_url = qbittorrentUrl.trim();
      if (qbittorrentUsername.trim()) fields.qbittorrent_username = qbittorrentUsername.trim();
      if (qbittorrentPassword.trim()) fields.qbittorrent_password = qbittorrentPassword.trim();
      // Contrairement aux cles/URLs ci-dessus, un dictionnaire vide est une
      // valeur explicite valide ("aucun mapping") : toujours envoye.
      fields.sonarr_path_mappings = sonarrPathMappings;
      fields.radarr_path_mappings = radarrPathMappings;

      const updated = await gapscanConfigWrite(fields, profile);
      setConfig(updated);
      setSonarrApiKey("");
      setRadarrApiKey("");
      setTrackerApiKey("");
      setTrackerAnnounceUrl("");
      setQbittorrentPassword("");
      setConfigSaved(true);
      setTimeout(() => setConfigSaved(false), 2000);
    } catch (e) {
      setConfigError(e instanceof ApiError ? e.message : "Enregistrement impossible.");
    } finally {
      setConfigSaving(false);
    }
  }

  async function handleExportCsv() {
    try {
      const blob = await gapscanExportCsv({
        status: statusFilter && statusFilter !== "not_verified" ? statusFilter : undefined,
        mediaType: mediaType || undefined,
        genre: trackerGenre || undefined,
        profile,
      });
      downloadBlob(blob, "gapscan.csv");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Export impossible.");
    }
  }

  async function handleClearLog() {
    try {
      await clearGapscanLog();
      setStatus((prev) => (prev ? { ...prev, log: [] } : prev));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Impossible de vider les logs.");
    }
  }

  const running = status?.state === "running";
  const notConfigured = config !== null && !config.tracker_configured;
  const noLibrary = config !== null && config.tracker_configured && !config.sonarr_configured && !config.radarr_configured;
  // Un scan precedent existe (memoire ou repris du disque au demarrage,
  // voir gapscan_results_store.py) des qu'un "done" a deja ete rapporte.
  const hasPreviousScan = status?.state === "done" && status.finished_at !== null;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-xl font-semibold text-ink">Bibliothèque</h1>
          <p className="text-sm text-ink-dim">
            Ta bibliothèque Sonarr/Radarr, annotée du statut {trackerDisplayName} dès qu'il est connu —
            sélectionne des titres à vérifier, ou lance un scan complet.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={only}
            onChange={(e) => setOnly(e.target.value as "" | "movies" | "series")}
            disabled={starting || running}
            aria-label="Bibliothèque à scanner"
            className="rounded-md border border-line-strong bg-surface px-2 py-2 text-sm text-ink"
          >
            <option value="">Films + séries</option>
            <option value="movies">Films seulement</option>
            <option value="series">Séries seulement</option>
          </select>
          {hasPreviousScan && (
            <label
              className="flex items-center gap-1.5 text-sm text-ink-dim"
              title="Reprend les titres déjà couverts et inchangés du dernier scan sans les réinterroger sur C411 — plus rapide."
            >
              <input
                type="checkbox"
                checked={incremental}
                onChange={(e) => setIncremental(e.target.checked)}
                disabled={starting || running}
                className="h-4 w-4 rounded border-line-strong"
              />
              Scan rapide
            </label>
          )}
          <button
            type="button"
            onClick={handleExportCsv}
            disabled={!items || items.length === 0}
            className="rounded-md border border-line-strong px-4 py-2 text-sm text-ink hover:bg-surface-2 disabled:opacity-50"
          >
            Export CSV
          </button>
          <button
            type="button"
            onClick={handleRun}
            disabled={starting || running || notConfigured || noLibrary}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90 disabled:opacity-50"
          >
            {running ? "Scan en cours…" : "Lancer un scan complet"}
          </button>
        </div>
      </div>

      <ActiveTransfersTray />

      {notConfigured && (
        <div className="rounded-md border border-warn bg-warn-bg px-4 py-3 text-sm text-warn">
          Clé API {trackerDisplayName} non configurée — renseigne-la ci-dessous.
        </div>
      )}
      {!notConfigured && noLibrary && (
        <div className="rounded-md border border-warn bg-warn-bg px-4 py-3 text-sm text-warn">
          Aucune instance Sonarr ni Radarr configurée — renseigne au moins l'une des deux ci-dessous.
        </div>
      )}

      <div className="rounded-md border border-line bg-surface">
        <button
          type="button"
          onClick={() => setShowConfigForm((v) => !v)}
          className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium text-ink"
        >
          Configuration (Sonarr, Radarr, {trackerDisplayName})
          <span className="text-ink-faint">{showConfigForm ? "▲" : "▼"}</span>
        </button>
        {showConfigForm && (
          <div className="space-y-3 border-t border-line p-4">
            <p className="text-xs text-ink-faint">
              Enregistré côté serveur ({" "}
              <code className="rounded bg-surface-2 px-1 font-mono">NFOGEN_GAPSCAN_CONFIG_FILE</code>{" "}
              requis). Un champ « clé » laissé vide ne modifie pas la clé déjà enregistrée.
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
                  placeholder={config?.sonarr_configured ? "•••• (enregistrée)" : ""}
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
                  placeholder={config?.radarr_configured ? "•••• (enregistrée)" : ""}
                  value={radarrApiKey}
                  onChange={(e) => setRadarrApiKey(e.target.value)}
                />
              </label>
              <label className="block text-sm font-medium text-ink-dim">
                URL de base {trackerDisplayName}
                <input
                  className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                  placeholder="https://c411.org"
                  value={trackerBaseUrl}
                  onChange={(e) => setTrackerBaseUrl(e.target.value)}
                />
              </label>
              <label className="block text-sm font-medium text-ink-dim">
                Clé API {trackerDisplayName}
                <input
                  className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                  type="password"
                  placeholder={config?.tracker_configured ? "•••• (enregistrée)" : ""}
                  value={trackerApiKey}
                  onChange={(e) => setTrackerApiKey(e.target.value)}
                />
              </label>
              <label className="block text-sm font-medium text-ink-dim">
                Adresse d'annonce {trackerDisplayName}
                <input
                  className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                  type="password"
                  placeholder={config?.tracker_announce_url_configured ? "•••• (enregistrée)" : ""}
                  value={trackerAnnounceUrl}
                  onChange={(e) => setTrackerAnnounceUrl(e.target.value)}
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
                  placeholder={config?.qbittorrent_configured ? "•••• (enregistré)" : ""}
                  value={qbittorrentPassword}
                  onChange={(e) => setQbittorrentPassword(e.target.value)}
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

            {configError && <p className="text-sm text-crit">{configError}</p>}

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={handleSaveConfig}
                disabled={configSaving}
                className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90 disabled:opacity-50"
              >
                {configSaving ? "Enregistrement…" : "Enregistrer"}
              </button>
              {configSaved && <span className="text-sm text-good">Enregistré.</span>}
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-md border border-crit bg-crit-bg px-4 py-3 text-sm text-crit">
          {error} — vérifiez les <Link to="/settings" className="underline">réglages de connexion</Link>.
        </div>
      )}

      {status && status.state === "error" && status.error && (
        <div className="rounded-md border border-crit bg-crit-bg px-4 py-3 text-sm text-crit">
          Le dernier scan a échoué : {status.error}
        </div>
      )}

      {running && (
        <div className="space-y-1 rounded-md border border-line bg-surface p-4">
          <p className="font-mono text-sm text-ink-dim">
            {status && status.total > 0
              ? `${status.processed} / ${status.total} titres traités…`
              : "Récupération de la bibliothèque…"}
          </p>
          <div className="h-2 w-full overflow-hidden rounded-full bg-surface-2">
            <div
              className="h-full bg-accent transition-all"
              style={{
                width: status && status.total > 0 ? `${(100 * status.processed) / status.total}%` : "10%",
              }}
            />
          </div>
        </div>
      )}

      {status && status.log.length > 0 && (
        <div className="space-y-2 rounded-md border border-line bg-surface p-4">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-ink-dim">Journal du scan</p>
            <button
              type="button"
              onClick={handleClearLog}
              className="text-xs text-ink-faint underline hover:text-ink"
            >
              Vider les logs
            </button>
          </div>
          <div className="max-h-40 space-y-0.5 overflow-y-auto font-mono text-xs text-ink-faint">
            {[...status.log].reverse().map((entry, i) => (
              <div key={i} className="flex items-center gap-2">
                <span
                  className={`whitespace-nowrap rounded-full px-1.5 py-0.5 text-[10px] ${STATUS_BADGE_CLASS[entry.status]}`}
                >
                  {statusLabel(entry.status, trackerDisplayName)}
                </span>
                <span>
                  {entry.title} {entry.year ? `(${entry.year})` : ""}
                  {entry.season_number ? ` S${String(entry.season_number).padStart(2, "0")}` : ""}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-end gap-3">
        <label className="block text-sm font-medium text-ink-dim">
          Recherche
          <input
            aria-label="Recherche"
            className="mt-1 w-full max-w-xs rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={q}
            onChange={(e) => resetPageAnd(setQ)(e.target.value)}
            placeholder="Titre…"
          />
        </label>
        <label className="block text-sm font-medium text-ink-dim">
          Type
          <select
            aria-label="Type"
            className="mt-1 w-full max-w-xs rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={mediaType}
            onChange={(e) => resetPageAnd(setMediaType)(e.target.value as "" | "movie" | "series")}
          >
            <option value="">Tous les types</option>
            <option value="movie">Films</option>
            <option value="series">Séries</option>
          </select>
        </label>
        <label className="block text-sm font-medium text-ink-dim">
          Genre
          <input
            aria-label="Genre"
            className="mt-1 w-full max-w-xs rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={genre}
            onChange={(e) => resetPageAnd(setGenre)(e.target.value)}
            placeholder="Action, Drama…"
          />
        </label>
        <label className="block text-sm font-medium text-ink-dim">
          Genre tracker
          <select
            aria-label="Genre tracker"
            className="mt-1 w-full max-w-xs rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={trackerGenre}
            onChange={(e) => resetPageAnd(setTrackerGenre)(e.target.value as "" | "anime" | "documentaire")}
          >
            <option value="">Tous</option>
            <option value="anime">Anime</option>
            <option value="documentaire">Documentaire</option>
          </select>
        </label>
        <label className="block text-sm font-medium text-ink-dim">
          Statut
          <select
            aria-label="Statut"
            className="mt-1 w-full max-w-xs rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={statusFilter}
            onChange={(e) => resetPageAnd(setStatusFilter)(e.target.value as GapStatus | "not_verified" | "")}
          >
            {STATUS_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm font-medium text-ink-dim">
          Ajouté depuis (jours)
          <input
            aria-label="Ajouté depuis (jours)"
            type="number"
            className="mt-1 w-full max-w-[8rem] rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={addedSinceDays}
            onChange={(e) => resetPageAnd(setAddedSinceDays)(e.target.value)}
          />
        </label>
        <label className="block text-sm font-medium text-ink-dim">
          Déjà traité
          <select
            aria-label="Déjà traité"
            className="mt-1 w-full max-w-xs rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={processed}
            onChange={(e) => resetPageAnd(setProcessed)(e.target.value as "" | "true" | "false")}
          >
            <option value="">Peu importe</option>
            <option value="true">Déjà traité</option>
            <option value="false">Jamais traité</option>
          </select>
        </label>
        <button
          type="button"
          onClick={selectAllFiltered}
          disabled={!items || items.length === 0}
          className="rounded-md border border-line-strong px-3 py-2 text-sm text-ink hover:bg-surface-2 disabled:opacity-50"
        >
          Tout sélectionner (filtré)
        </button>
        <button
          type="button"
          onClick={clearSelection}
          disabled={selected.size === 0}
          className="rounded-md border border-line-strong px-3 py-2 text-sm text-ink hover:bg-surface-2 disabled:opacity-50"
        >
          Désélectionner
        </button>
        <button
          type="button"
          onClick={handleVerifySelection}
          disabled={selected.size === 0 || starting || running}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90 disabled:opacity-50"
        >
          Vérifier sur le tracker ({selected.size} sélectionnés)
        </button>
      </div>

      {items === null && !error && <p className="text-sm text-ink-faint">Chargement…</p>}
      {items !== null && items.length === 0 && <p className="text-sm text-ink-faint">Aucun résultat.</p>}

      {items !== null && items.length > 0 && (
        <table className="w-full overflow-hidden rounded-md border border-line bg-surface text-sm">
          <thead className="bg-surface-2 text-left text-ink-dim">
            <tr>
              <th className="px-4 py-2" />
              <th className="px-4 py-2">Titre</th>
              <th className="px-4 py-2">Type</th>
              <th className="px-4 py-2">Genres</th>
              <th className="px-4 py-2">Statut</th>
              <th className="px-4 py-2">Ta version</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.key} className="border-t border-line">
                <td className="px-4 py-2">
                  <input
                    type="checkbox"
                    aria-label={item.title}
                    checked={selected.has(item.key)}
                    onChange={() => toggleOne(item.key)}
                    className="h-4 w-4 rounded border-line-strong"
                  />
                </td>
                <td className="px-4 py-2 font-mono font-medium text-ink">
                  {item.title} {item.year ? `(${item.year})` : ""}
                  {item.status !== null && !item.path_resolved && (
                    <span
                      className="ml-1 rounded-full bg-warn-bg px-2 py-0.5 text-xs text-warn"
                      title={item.path_error ?? "Chemin local non résolu"}
                    >
                      ⚠ chemin
                    </span>
                  )}
                </td>
                <td className="px-4 py-2 text-ink-dim">
                  {item.media_type === "movie" ? "Film" : `Série S${String(item.season_number).padStart(2, "0")}`}
                </td>
                <td className="px-4 py-2 text-ink-dim">{item.genres.join(", ") || "—"}</td>
                <td className="whitespace-nowrap px-4 py-2">
                  <span
                    className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs ${
                      item.status === null ? NOT_VERIFIED_BADGE_CLASS : STATUS_BADGE_CLASS[item.status]
                    }`}
                    title={item.status === "error" ? item.error ?? undefined : undefined}
                  >
                    {statusLabel(item.status, trackerDisplayName)}
                  </span>
                  {item.has_freeleech_alternative && (
                    <span className="ml-1 rounded-full bg-good-bg px-2 py-0.5 text-xs text-good">FL</span>
                  )}
                  {item.has_double_upload_window && (
                    <span className="ml-1 rounded-full bg-info-bg px-2 py-0.5 text-xs text-info">2x</span>
                  )}
                </td>
                <td className="whitespace-nowrap px-4 py-2 font-mono text-ink-dim">
                  {qualitySummary(item.local_quality)}
                </td>
                <td className="whitespace-nowrap px-4 py-2 text-right">
                  <Link to="/" className="text-sm text-accent-ink underline">
                    Générer
                  </Link>
                  {item.path_resolved && item.local_paths.length > 0 && (
                    <button
                      type="button"
                      onClick={() =>
                        setActiveUpload({
                          title: item.title,
                          localPaths: item.local_paths,
                          mediaType: item.media_type,
                          radarrMovieId: item.radarr_movie_id,
                          sonarrSeriesId: item.sonarr_series_id,
                          tmdbId: item.tmdb_id ? Number(item.tmdb_id) : null,
                          tvdbId: item.tvdb_id,
                          genre: item.tracker_genre,
                          seasonNumber: item.season_number,
                        })
                      }
                      className="ml-3 text-sm text-accent-ink underline"
                    >
                      Préparer l'upload
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm text-ink-dim">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded-md border border-line-strong px-3 py-1.5 disabled:opacity-50"
          >
            Précédent
          </button>
          <span>
            Page {page} / {Math.max(1, Math.ceil(total / PAGE_SIZE))} — {total} résultats
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => (p * PAGE_SIZE < total ? p + 1 : p))}
            disabled={page * PAGE_SIZE >= total}
            className="rounded-md border border-line-strong px-3 py-1.5 disabled:opacity-50"
          >
            Suivant
          </button>
        </div>
      )}

      {activeUpload && (
        // key force un demontage/remontage complet quand on ouvre un
        // "Preparer l'upload" different SANS fermer le precedent -- sinon
        // React reutilise la meme instance et son etat interne (titre
        // corrige, apercu deja charge) reste celui de la ligne precedente
        // (incident reel, 2026-08-28 : titre vide/perime en changeant de
        // ligne sans cliquer Fermer entre les deux).
        <UploadPrepPanel
          key={activeUpload.localPaths.join("|")}
          localPaths={activeUpload.localPaths}
          title={activeUpload.title}
          mediaType={activeUpload.mediaType}
          radarrMovieId={activeUpload.radarrMovieId}
          sonarrSeriesId={activeUpload.sonarrSeriesId}
          tmdbId={activeUpload.tmdbId}
          tvdbId={activeUpload.tvdbId}
          genre={activeUpload.genre}
          seasonNumber={activeUpload.seasonNumber}
          onClose={() => setActiveUpload(null)}
        />
      )}
    </div>
  );
}
