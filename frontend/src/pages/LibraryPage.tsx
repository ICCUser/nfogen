import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import ActiveTransfersTray from "../components/ActiveTransfersTray";
import UploadPrepPanel from "../components/UploadPrepPanel";
import {
  cancelSeedMatchJob,
  clearGapscanLog,
  downloadBlob,
  gapscanConfig,
  gapscanConfigWrite,
  gapscanExportCsv,
  gapscanRun,
  gapscanStatus,
  libraryResults,
  refreshLibrary,
  seedMatchJobStatus,
  startSeedMatch,
} from "../api/client";
import { ApiError } from "../api/types";
import type {
  GapscanConfig,
  GapscanConfigWrite,
  GapscanStatus,
  GapStatus,
  LibraryItem,
  SeasonPackRequest,
  SeasonPackSuggestion,
  SeedMatchJob,
} from "../api/types";
import { useProfile } from "../ProfileContext";
import { formatBytes } from "../format";

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

/** Date relative ("il y a 3 j") -- LibraryItem.added_at (retour
 * utilisateur, 2026-09-09) etait deja connu (utilise par le filtre
 * added_since_days) mais jamais affiche en colonne. */
function formatAddedAt(addedAt: number | null): string {
  if (addedAt === null) return "—";
  const days = Math.floor((Date.now() / 1000 - addedAt) / 86400);
  if (days <= 0) return "aujourd'hui";
  if (days === 1) return "hier";
  if (days < 30) return `il y a ${days} j`;
  const months = Math.floor(days / 30);
  if (months < 12) return `il y a ${months} mois`;
  const years = Math.floor(months / 12);
  return `il y a ${years} an${years > 1 ? "s" : ""}`;
}

const LIBRARY_COLUMNS: ColumnDef<LibraryItem>[] = [
  { id: "select", header: "", enableSorting: false },
  { id: "title", header: "Titre", accessorKey: "title" },
  { id: "media_type", header: "Type", accessorKey: "media_type" },
  { id: "genres", header: "Genres", enableSorting: false },
  { id: "status", header: "Statut", accessorKey: "status" },
  { id: "team", header: "Team", accessorKey: "team" },
  { id: "quality", header: "Ta version", accessorFn: (row) => row.local_quality.resolution ?? 0 },
  { id: "size_bytes", header: "Taille", accessorKey: "size_bytes" },
  { id: "added_at", header: "Ajouté le", accessorKey: "added_at" },
  { id: "actions", header: "", enableSorting: false },
];

const PAGE_SIZE = 50;

/** Barre de pagination -- rendue au-dessus ET en dessous du tableau
 * (retour utilisateur, 2026-09-09 : "les tableaux sont trop longs [...]
 * ne permettent pas un retour a la premiere page directement"). */
function PaginationBar({
  page, total, pageSize, onFirst, onPrev, onNext,
}: {
  page: number; total: number; pageSize: number;
  onFirst: () => void; onPrev: () => void; onNext: () => void;
}) {
  if (total <= pageSize) return null;
  return (
    <div className="flex items-center justify-between text-sm text-ink-dim">
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onFirst}
          disabled={page <= 1}
          className="rounded-md border border-line-strong px-3 py-1.5 disabled:opacity-50"
        >
          Première page
        </button>
        <button
          type="button"
          onClick={onPrev}
          disabled={page <= 1}
          className="rounded-md border border-line-strong px-3 py-1.5 disabled:opacity-50"
        >
          Précédent
        </button>
      </div>
      <span>
        Page {page} / {Math.max(1, Math.ceil(total / pageSize))} — {total} résultats
      </span>
      <button
        type="button"
        onClick={onNext}
        disabled={page * pageSize >= total}
        className="rounded-md border border-line-strong px-3 py-1.5 disabled:opacity-50"
      >
        Suivant
      </button>
    </div>
  );
}

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
  const [seasonPacks, setSeasonPacks] = useState<SeasonPackSuggestion[]>([]);
  // Seed d'une release C411 deja possedee, sans re-upload (retour
  // utilisateur, 2026-09-09) -- cle : LibraryItem.key, comme les autres
  // etats indexes par ligne de ce composant.
  const [seedMatchJobs, setSeedMatchJobs] = useState<Record<string, SeedMatchJob>>({});
  const [q, setQ] = useState("");
  // Recherche texte debouncee (retour utilisateur, 2026-09-08 : "5 a 10
  // secondes apres chaque frappe" -- sans ca, chaque caractere tape
  // relancait un appel complet /gapscan/library, potentiellement couteux
  // cote Sonarr, voir plus bas). `q` reste la valeur immediate affichee
  // dans le champ ; `debouncedQ` (utilisee par load()) ne se met a jour
  // que 400ms apres la derniere frappe.
  const [debouncedQ, setDebouncedQ] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQ(q), 400);
    return () => window.clearTimeout(timer);
  }, [q]);
  const [mediaType, setMediaType] = useState<"" | "movie" | "series">("");
  const [genre, setGenre] = useState("");
  const [trackerGenre, setTrackerGenre] = useState<"" | "anime" | "documentaire">("");
  const [statusFilter, setStatusFilter] = useState<GapStatus | "not_verified" | "">("");
  const [addedSinceDays, setAddedSinceDays] = useState("");
  const [processed, setProcessed] = useState<"" | "true" | "false">("");
  const [page, setPage] = useState(1);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [error, setError] = useState<string | null>(null);
  const [syncedAt, setSyncedAt] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
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
    seasonPack?: SeasonPackRequest;
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

  // Formulaire de configuration DU PROFIL (namespacee par profil cote
  // serveur : cle API, URL de base et d'annonce du tracker). La config
  // GLOBALE (Sonarr/Radarr/qBittorrent/TMDB/mise en scene/mappings) a
  // migre vers la page Reglages (retour utilisateur, 2026-09-07 -- ces
  // reglages ne sont pas lies au profil de tracker, ils n'ont pas leur
  // place sur la page Bibliotheque). Replie par defaut, deplie
  // automatiquement une fois qu'on sait qu'il manque quelque chose (voir
  // l'effet plus bas, une fois `config` charge).
  const [showProfileConfigForm, setShowProfileConfigForm] = useState(false);
  const [profileConfigSaving, setProfileConfigSaving] = useState(false);
  const [profileConfigSaved, setProfileConfigSaved] = useState(false);
  const [profileConfigError, setProfileConfigError] = useState<string | null>(null);
  const [trackerApiKey, setTrackerApiKey] = useState("");
  const [trackerBaseUrl, setTrackerBaseUrl] = useState("");
  const [trackerAnnounceUrl, setTrackerAnnounceUrl] = useState("");

  useEffect(() => {
    gapscanConfig(profile)
      .catch(() => null)
      .then((c) => {
        if (!c) return;
        setConfig(c);
        setTrackerBaseUrl(c.tracker_base_url ?? "");
        if (!c.tracker_configured) setShowProfileConfigForm(true);
      });
    refreshStatus();
    return () => stopPolling();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    debouncedQ, mediaType, genre, trackerGenre, statusFilter, addedSinceDays, processed, page, profile,
    sorting,
  ]);

  function resetPageAnd<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v);
      setPage(1);
    };
  }

  /** Changer de tri revient a la page 1 -- meme logique que resetPageAnd
   * pour les filtres (retour utilisateur, 2026-09-09). */
  function handleSortingChange(updater: SortingState | ((old: SortingState) => SortingState)) {
    setSorting((old) => {
      const next = typeof updater === "function" ? updater(old) : updater;
      setPage(1);
      return next;
    });
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
      const activeSort = sorting[0];
      const res = await libraryResults({
        q: debouncedQ || undefined,
        mediaType: mediaType || undefined,
        genre: genre || undefined,
        trackerGenre: trackerGenre || undefined,
        status: statusFilter || undefined,
        addedSinceDays: addedSinceDays ? Number(addedSinceDays) : undefined,
        processed: processed === "" ? undefined : processed === "true",
        sort: activeSort?.id,
        order: activeSort ? (activeSort.desc ? "desc" : "asc") : undefined,
        page,
        pageSize: PAGE_SIZE,
        profile,
      });
      setItems(res.items);
      setTotal(res.total);
      setSeasonPacks(res.season_packs);
      setSyncedAt(res.synced_at ?? null);
    } catch (e) {
      setItems(null);
      setTotal(0);
      setError(e instanceof ApiError ? e.message : "Bibliothèque indisponible.");
    }
  }

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await refreshLibrary();
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Rafraîchissement impossible.");
    } finally {
      setRefreshing(false);
    }
  }

  function formatSyncedAt(ts: number | null): string {
    if (ts === null) return "jamais synchronisé";
    const minutes = Math.round((Date.now() / 1000 - ts) / 60);
    if (minutes < 1) return "à l'instant";
    if (minutes < 60) return `il y a ${minutes} min`;
    return `il y a ${Math.round(minutes / 60)} h`;
  }

  // Resout les chemins locaux par saison pour un SeasonPackSuggestion, a
  // partir des lignes actuellement affichees (`items`). Limitation connue
  // (retour utilisateur, 2026-09-08) : une saison absente de la page/du
  // filtre courant (recherche, pagination) ne peut pas etre resolue ici --
  // le bouton "Preparer le pack" reste desactive dans ce cas (voir
  // seasonsForPack ci-dessous, valeur null si une saison manque).
  function seasonsForPack(pack: SeasonPackSuggestion): SeasonPackRequest["seasons"] | null {
    if (!items) return null;
    const seasons: SeasonPackRequest["seasons"] = [];
    for (const seasonNumber of pack.season_numbers) {
      const match = items.find(
        (i) => i.sonarr_series_id === pack.sonarr_series_id && i.season_number === seasonNumber,
      );
      if (!match || match.local_paths.length === 0) return null;
      seasons.push({ season_number: seasonNumber, local_paths: match.local_paths });
    }
    return seasons;
  }

  async function pollSeedMatchUntilTerminal(key: string, jobId: string) {
    for (;;) {
      const job = await seedMatchJobStatus(jobId);
      setSeedMatchJobs((prev) => ({ ...prev, [key]: job }));
      if (["done", "mismatch", "error", "cancelled"].includes(job.state)) return;
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
    }
  }

  async function handleStartSeedMatch(item: LibraryItem) {
    if (!item.seed_match) return;
    try {
      const { job_id } = await startSeedMatch(item.key, item.seed_match.guid, item.seed_match.release_name);
      await pollSeedMatchUntilTerminal(item.key, job_id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Impossible de démarrer le seed.");
    }
  }

  async function handleCancelSeedMatch(key: string) {
    const job = seedMatchJobs[key];
    if (!job) return;
    try {
      await cancelSeedMatchJob(job.job_id);
    } catch {
      // best effort -- le prochain poll reflete l'etat reel de toute facon
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

  // Config DU PROFIL (namespacee par `profile` cote serveur : voir
  // gapscan_config_store.write(), branche `tracker_updates`).
  async function handleSaveProfileConfig() {
    setProfileConfigSaving(true);
    setProfileConfigError(null);
    setProfileConfigSaved(false);
    try {
      // Seuls les champs non vides sont envoyes : un champ cle laisse vide
      // ne doit pas effacer une valeur deja enregistree (PUT partiel cote
      // serveur, voir gapscan_config_store.write()).
      const fields: GapscanConfigWrite = {};
      if (trackerApiKey.trim()) fields.tracker_api_key = trackerApiKey.trim();
      if (trackerBaseUrl.trim()) fields.tracker_base_url = trackerBaseUrl.trim();
      if (trackerAnnounceUrl.trim()) fields.tracker_announce_url = trackerAnnounceUrl.trim();

      const updated = await gapscanConfigWrite(fields, profile);
      setConfig(updated);
      setTrackerApiKey("");
      setTrackerAnnounceUrl("");
      setProfileConfigSaved(true);
      setTimeout(() => setProfileConfigSaved(false), 2000);
    } catch (e) {
      setProfileConfigError(e instanceof ApiError ? e.message : "Enregistrement impossible.");
    } finally {
      setProfileConfigSaving(false);
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

  const table = useReactTable({
    data: items ?? [],
    columns: LIBRARY_COLUMNS,
    state: { sorting },
    onSortingChange: handleSortingChange,
    manualSorting: true,
    enableMultiSort: false,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-xl font-semibold text-ink">Bibliothèque</h1>
          <p className="text-sm text-ink-dim">
            Ta bibliothèque Sonarr/Radarr, annotée du statut {trackerDisplayName} dès qu'il est connu —
            sélectionne des titres à vérifier, ou lance un scan complet.
          </p>
          <p className="text-xs text-ink-dim">Dernière synchro : {formatSyncedAt(syncedAt)}</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink hover:bg-surface-hover disabled:opacity-50"
          >
            {refreshing ? "Rafraîchissement…" : "Rafraîchir"}
          </button>
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
          Aucune instance Sonarr ni Radarr configurée — renseigne au moins l'une des deux dans les{" "}
          <Link to="/settings" className="underline">Réglages</Link>.
        </div>
      )}

      <div className="rounded-md border border-line bg-surface">
        <button
          type="button"
          onClick={() => setShowProfileConfigForm((v) => !v)}
          className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium text-ink"
        >
          Configuration du profil {trackerDisplayName} ({profile})
          <span className="text-ink-faint">{showProfileConfigForm ? "▲" : "▼"}</span>
        </button>
        {showProfileConfigForm && (
          <div className="space-y-3 border-t border-line p-4">
            <p className="text-xs text-ink-faint">
              Propre à ce profil de tracker — un autre profil peut avoir sa propre clé/URL (voir
              le sélecteur de profil dans l'en-tête). Enregistré côté serveur ({" "}
              <code className="rounded bg-surface-2 px-1 font-mono">NFOGEN_GAPSCAN_CONFIG_FILE</code>{" "}
              requis). Un champ « clé » laissé vide ne modifie pas la clé déjà enregistrée.
            </p>

            <div className="grid grid-cols-2 gap-3">
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
            </div>

            {profileConfigError && <p className="text-sm text-crit">{profileConfigError}</p>}

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={handleSaveProfileConfig}
                disabled={profileConfigSaving}
                className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90 disabled:opacity-50"
              >
                {profileConfigSaving ? "Enregistrement…" : "Enregistrer"}
              </button>
              {profileConfigSaved && <span className="text-sm text-good">Enregistré.</span>}
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

      {seasonPacks.length > 0 && (
        <div className="space-y-2 rounded-md border border-line bg-surface p-4">
          <p className="text-sm font-medium text-ink-dim">Packs disponibles</p>
          {seasonPacks.map((pack) => {
            const seasons = seasonsForPack(pack);
            const label = pack.is_full_series
              ? "INTEGRALE"
              : `S${String(pack.season_numbers[0]).padStart(2, "0")}S${String(
                  pack.season_numbers[pack.season_numbers.length - 1],
                ).padStart(2, "0")}`;
            return (
              <div
                key={`${pack.sonarr_series_id}-${pack.season_numbers.join("-")}`}
                className="flex items-center justify-between text-sm"
              >
                <span>
                  {pack.title} — {label} ({pack.team})
                </span>
                <button
                  type="button"
                  disabled={seasons === null}
                  title={
                    seasons === null
                      ? "Certaines saisons de ce pack ne sont pas visibles dans la page/le filtre actuel."
                      : undefined
                  }
                  onClick={() => {
                    if (seasons === null) return;
                    setActiveUpload({
                      title: `${pack.title} ${label}`,
                      localPaths: seasons.flatMap((s) => s.local_paths),
                      mediaType: "series",
                      radarrMovieId: null,
                      sonarrSeriesId: pack.sonarr_series_id,
                      tmdbId: null,
                      tvdbId: null,
                      genre: null,
                      seasonNumber: null,
                      seasonPack: {
                        title: pack.title,
                        team: pack.team,
                        is_full_series: pack.is_full_series,
                        seasons,
                      },
                    });
                  }}
                  className="rounded-md border border-line-strong px-3 py-1.5 text-xs text-ink hover:bg-surface-2 disabled:opacity-50"
                >
                  Préparer le pack
                </button>
              </div>
            );
          })}
        </div>
      )}

      {items === null && !error && <p className="text-sm text-ink-faint">Chargement…</p>}
      {items !== null && items.length === 0 && <p className="text-sm text-ink-faint">Aucun résultat.</p>}

      {items !== null && items.length > 0 && (
        <PaginationBar
          page={page} total={total} pageSize={PAGE_SIZE}
          onFirst={() => setPage(1)}
          onPrev={() => setPage((p) => Math.max(1, p - 1))}
          onNext={() => setPage((p) => (p * PAGE_SIZE < total ? p + 1 : p))}
        />
      )}

      {items !== null && items.length > 0 && (
        <table className="w-full overflow-hidden rounded-md border border-line bg-surface text-sm">
          <thead className="bg-surface-2 text-left text-ink-dim">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    data-testid={`col-header-${header.column.id}`}
                    className={`px-4 py-2 ${header.column.getCanSort() ? "cursor-pointer select-none" : ""}`}
                    onClick={header.column.getToggleSortingHandler()}
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    {header.column.getIsSorted() === "asc" && " ▲"}
                    {header.column.getIsSorted() === "desc" && " ▼"}
                  </th>
                ))}
              </tr>
            ))}
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
                <td className="whitespace-nowrap px-4 py-2 font-mono text-ink-dim">{item.team ?? "—"}</td>
                <td className="whitespace-nowrap px-4 py-2 font-mono text-ink-dim">
                  {qualitySummary(item.local_quality)}
                </td>
                <td className="whitespace-nowrap px-4 py-2 text-ink-dim">
                  {item.size_bytes !== null ? formatBytes(item.size_bytes) : "—"}
                </td>
                <td className="whitespace-nowrap px-4 py-2 text-ink-dim">
                  {formatAddedAt(item.added_at)}
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
                  {item.seed_match && !seedMatchJobs[item.key] && (
                    <button
                      type="button"
                      onClick={() => handleStartSeedMatch(item)}
                      className="ml-3 text-sm text-accent-ink underline"
                    >
                      Seed possible
                    </button>
                  )}
                  {seedMatchJobs[item.key]
                    && seedMatchJobs[item.key].state !== "done"
                    && seedMatchJobs[item.key].state !== "mismatch"
                    && seedMatchJobs[item.key].state !== "error" && (
                    <span className="ml-3 text-xs text-ink-dim">
                      Vérification…
                      <button
                        type="button"
                        onClick={() => handleCancelSeedMatch(item.key)}
                        className="ml-1 text-crit underline"
                      >
                        Annuler
                      </button>
                    </span>
                  )}
                  {seedMatchJobs[item.key]?.state === "done" && (
                    <span className="ml-3 text-xs text-good">✅ En seed</span>
                  )}
                  {seedMatchJobs[item.key]?.state === "mismatch" && (
                    <span
                      className="ml-3 text-xs text-warn"
                      title={seedMatchJobs[item.key].result?.warning ?? undefined}
                    >
                      ⚠ {seedMatchJobs[item.key].result?.warning}
                    </span>
                  )}
                  {seedMatchJobs[item.key]?.state === "error" && (
                    <span className="ml-3 text-xs text-crit">⚠ {seedMatchJobs[item.key].error}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {items !== null && items.length > 0 && (
        <PaginationBar
          page={page} total={total} pageSize={PAGE_SIZE}
          onFirst={() => setPage(1)}
          onPrev={() => setPage((p) => Math.max(1, p - 1))}
          onNext={() => setPage((p) => (p * PAGE_SIZE < total ? p + 1 : p))}
        />
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
          seasonPack={activeUpload.seasonPack}
          onClose={() => setActiveUpload(null)}
        />
      )}
    </div>
  );
}
