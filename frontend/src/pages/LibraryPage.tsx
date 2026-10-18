import { Check, ChevronDown, SlidersHorizontal, TriangleAlert, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  type ColumnDef,
  type SortingState,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import ActiveTransfersTray from "../components/ActiveTransfersTray";
import InlineBanner from "../components/InlineBanner";
import PageToolbar from "../components/PageToolbar";
import ProgressBar from "../components/ProgressBar";
import SortableHeader from "../components/SortableHeader";
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
import { useProfile } from "../useProfile";
import { formatBytes } from "../format";
import Button from "../components/Button";

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
        <Button
          variant="secondary"
          onClick={onFirst}
          disabled={page <= 1}
        >
          Première page
        </Button>
        <Button
          variant="secondary"
          onClick={onPrev}
          disabled={page <= 1}
        >
          Précédent
        </Button>
      </div>
      <span>
        Page {page} / {Math.max(1, Math.ceil(total / pageSize))} — {total} résultats
      </span>
      <Button
        variant="secondary"
        onClick={onNext}
        disabled={page * pageSize >= total}
      >
        Suivant
      </Button>
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
  // Replie par defaut (retour utilisateur, 2026-09-13 : "prenne trop de
  // place" -- une bibliotheque bien remplie peut suggerer des dizaines
  // de packs, chacun sa ligne, poussant le tableau hors ecran).
  const [packsExpanded, setPacksExpanded] = useState(false);
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
  // Filtres secondaires replies par defaut (audit front 2026-10-14, lot 6 :
  // 7 filtres + 3 boutons de selection au meme niveau repoussaient le
  // tableau sous la ligne de flottaison, surtout sur mobile). Le bouton
  // "Filtres" affiche combien sont actifs, pour qu'un filtre cache ne
  // fasse jamais disparaitre des lignes sans explication.
  const [showMoreFilters, setShowMoreFilters] = useState(false);
  const advancedFilterCount = [genre, trackerGenre, addedSinceDays, processed].filter((v) => v !== "").length;
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
  // Distinct de `activeUpload` : le tiroir reste monte (contenu intact)
  // pendant son animation de sortie, `activeUpload` n'est vide qu'une fois
  // celle-ci terminee (onExited, voir Drawer -- audit front 2026-10-14).
  const [uploadOpen, setUploadOpen] = useState(false);
  // Un groupe est mis en scene mais pas encore envoye (signale par
  // UploadPrepPanel) : fermer le tiroir le garde alors MONTE (etat intact)
  // et un bandeau permet de le reprendre -- remplace l'ancien confirm() a
  // la fermeture (audit front 2026-10-14, lot 4 : fermer n'est pas
  // destructif, rien ne doit l'interrompre).
  const [uploadPending, setUploadPending] = useState(false);
  // Autre ligne demandee alors qu'un upload attend : on demande d'abord,
  // dans le bandeau, s'il faut abandonner celui en attente.
  const [replaceCandidate, setReplaceCandidate] = useState<NonNullable<typeof activeUpload> | null>(null);
  function openUpload(upload: NonNullable<typeof activeUpload>) {
    const same = activeUpload !== null && activeUpload.localPaths.join("|") === upload.localPaths.join("|");
    if (activeUpload !== null && uploadPending && !same) {
      setReplaceCandidate(upload);
      return;
    }
    setReplaceCandidate(null);
    if (!same) setUploadPending(false);
    setActiveUpload(upload);
    setUploadOpen(true);
  }
  function abandonPendingUpload(next: NonNullable<typeof activeUpload> | null) {
    setReplaceCandidate(null);
    setUploadPending(false);
    setActiveUpload(next);
    setUploadOpen(next !== null);
  }

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

  /** Case de l'en-tete du tableau : coche/decoche toutes les lignes de la
   * page affichee (remplace le bouton "Tout sélectionner (filtré)"). Une
   * selection faite sur d'autres pages est conservee. */
  function togglePageSelection() {
    if (!items) return;
    const pageKeys = items.map((i) => i.key);
    setSelected((prev) => {
      const next = new Set(prev);
      const allSelected = pageKeys.every((k) => next.has(k));
      for (const k of pageKeys) {
        if (allSelected) next.delete(k);
        else next.add(k);
      }
      return next;
    });
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

  const pageSelectedCount = items ? items.filter((i) => selected.has(i.key)).length : 0;
  const pageSelection: "none" | "some" | "all" =
    !items || items.length === 0 || pageSelectedCount === 0
      ? "none"
      : pageSelectedCount === items.length
        ? "all"
        : "some";
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
    <div className={`space-y-4 ${selected.size > 0 ? "pb-24" : ""}`}>
      <PageToolbar title="Bibliothèque" subtitle={`Dernière synchro : ${formatSyncedAt(syncedAt)}`}>
        <Button
          variant="secondary"
          onClick={handleRefresh}
          disabled={refreshing}
        >
          {refreshing ? "Rafraîchissement…" : "Rafraîchir"}
        </Button>
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
        <Button
          variant="secondary"
          onClick={handleExportCsv}
          disabled={!items || items.length === 0}
        >
          Export CSV
        </Button>
        <Button
          variant="primary"
          onClick={handleRun}
          disabled={starting || running || notConfigured || noLibrary}
        >
          {running ? "Scan en cours…" : "Lancer un scan complet"}
        </Button>
      </PageToolbar>
      <p className="text-sm text-ink-dim">
        Ta bibliothèque Sonarr/Radarr, annotée du statut {trackerDisplayName} dès qu'il est connu — sélectionne
        des titres à vérifier, ou lance un scan complet.
      </p>

      <ActiveTransfersTray />

      {activeUpload && uploadPending && !uploadOpen && (
        <div
          role="status"
          className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-info bg-info-bg px-4 py-3 text-sm text-info"
        >
          <span>
            {replaceCandidate
              ? `« ${activeUpload.title} » est prêt mais pas encore envoyé. L'abandonner pour préparer « ${replaceCandidate.title} » ?`
              : `« ${activeUpload.title} » est prêt (mis en scène, .torrent créé) mais pas encore envoyé.`}
          </span>
          <span className="flex flex-wrap gap-2">
            <Button variant="primary" size="sm" onClick={() => openUpload(activeUpload)}>
              Reprendre
            </Button>
            <Button variant="secondary" size="sm" onClick={() => abandonPendingUpload(replaceCandidate)}>
              {replaceCandidate ? `Abandonner et préparer « ${replaceCandidate.title} »` : "Abandonner"}
            </Button>
          </span>
        </div>
      )}

      {notConfigured && (
        <div role="status" className="rounded-md border border-warn bg-warn-bg px-4 py-3 text-sm text-warn">
          Clé API {trackerDisplayName} non configurée — renseigne-la ci-dessous.
        </div>
      )}
      {!notConfigured && noLibrary && (
        <div role="status" className="rounded-md border border-warn bg-warn-bg px-4 py-3 text-sm text-warn">
          Aucune instance Sonarr ni Radarr configurée — renseigne au moins l'une des deux dans les{" "}
          <Link to="/settings" className="underline">Réglages</Link>.
        </div>
      )}

      <div className="rounded-md border border-line bg-surface">
        <button
          type="button"
          onClick={() => setShowProfileConfigForm((v) => !v)}
          aria-expanded={showProfileConfigForm}
          className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium text-ink transition-colors duration-100 hover:bg-surface-2 active:bg-line"
        >
          Configuration du profil {trackerDisplayName} ({profile})
          <ChevronDown
            size={16}
            aria-hidden="true"
            className={`text-ink-faint transition-transform duration-200 motion-reduce:transition-none ${showProfileConfigForm ? "rotate-180" : ""}`}
          />
        </button>
        {showProfileConfigForm && (
          // Toute modification d'un champ efface "Enregistré." (l'evenement
          // change des champs remonte jusqu'ici).
          <div className="space-y-3 border-t border-line p-4" onChange={() => setProfileConfigSaved(false)}>
            <p className="text-xs text-ink-faint">
              Propre à ce profil de tracker — un autre profil peut avoir sa propre clé/URL (voir
              le sélecteur de profil dans l'en-tête). Enregistré côté serveur ({" "}
              <code className="rounded bg-surface-2 px-1 font-mono">NFOGEN_GAPSCAN_CONFIG_FILE</code>{" "}
              requis). Un champ « clé » laissé vide ne modifie pas la clé déjà enregistrée.
            </p>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
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

            {profileConfigError && <p role="alert" className="text-sm text-crit">{profileConfigError}</p>}

            <div className="flex items-center gap-3">
              <Button
                variant="primary"
                onClick={handleSaveProfileConfig}
                disabled={profileConfigSaving}
              >
                {profileConfigSaving ? "Enregistrement…" : "Enregistrer"}
              </Button>
              {/* Region live toujours presente, message persistant jusqu'a
                  la prochaine modification (audit front 2026-10-14, lot 4). */}
              <span role="status" className="text-sm text-good">
                {profileConfigSaved ? "Enregistré." : ""}
              </span>
            </div>
          </div>
        )}
      </div>

      {error && (
        <div role="alert" className="rounded-md border border-crit bg-crit-bg px-4 py-3 text-sm text-crit">
          {error} — vérifiez les <Link to="/settings" className="underline">réglages de connexion</Link>.
        </div>
      )}

      {status && status.state === "error" && status.error && (
        <div role="alert" className="rounded-md border border-crit bg-crit-bg px-4 py-3 text-sm text-crit">
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
          {/* Total encore inconnu (recuperation de la bibliotheque) : barre
              indeterminee plutot qu'un "10 %" fige (audit front 2026-10-14,
              lot 7). */}
          <ProgressBar
            value={status && status.total > 0 ? (100 * status.processed) / status.total : null}
            label="Progression du scan"
          />
        </div>
      )}

      {status && status.log.length > 0 && (
        <div className="space-y-2 rounded-md border border-line bg-surface p-4">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-ink-dim">Journal du scan</p>
            <Button
              variant="link-muted"
              onClick={handleClearLog}
              className="text-xs"
            >
              Vider les logs
            </Button>
          </div>
          <div className="max-h-40 space-y-0.5 overflow-y-auto font-mono text-xs text-ink-faint">
            {[...status.log].reverse().map((entry, i) => (
              <div key={i} className="flex items-center gap-2">
                <span
                  className={`whitespace-nowrap rounded-full px-1.5 py-0.5 text-[11px] ${STATUS_BADGE_CLASS[entry.status]}`}
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

      <div className="space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="block text-sm font-medium text-ink-dim">
            Recherche
            <input
              aria-label="Recherche"
              className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink sm:w-48"
              value={q}
              onChange={(e) => resetPageAnd(setQ)(e.target.value)}
              placeholder="Titre…"
            />
          </label>
          <label className="block text-sm font-medium text-ink-dim">
            Type
            <select
              aria-label="Type"
              className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink sm:w-48"
              value={mediaType}
              onChange={(e) => resetPageAnd(setMediaType)(e.target.value as "" | "movie" | "series")}
            >
              <option value="">Tous les types</option>
              <option value="movie">Films</option>
              <option value="series">Séries</option>
            </select>
          </label>
          <label className="block text-sm font-medium text-ink-dim">
            Statut
            <select
              aria-label="Statut"
              className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink sm:w-48"
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
          <Button
            variant="secondary"
            aria-expanded={showMoreFilters}
            aria-controls="library-more-filters"
            aria-label={
              advancedFilterCount > 0
                ? `Filtres, ${advancedFilterCount} actif${advancedFilterCount > 1 ? "s" : ""}`
                : "Filtres"
            }
            onClick={() => setShowMoreFilters((v) => !v)}
            className="inline-flex items-center gap-1.5"
          >
            <SlidersHorizontal size={14} aria-hidden="true" />
            Filtres
            {advancedFilterCount > 0 && (
              <span aria-hidden="true" className="rounded-full bg-accent px-1.5 text-xs font-medium text-surface">
                {advancedFilterCount}
              </span>
            )}
          </Button>
        </div>
        {showMoreFilters && (
          <div id="library-more-filters" className="flex flex-wrap items-end gap-3 rounded-md border border-line bg-surface-2 p-3">
            <label className="block text-sm font-medium text-ink-dim">
              Genre
              <input
                aria-label="Genre"
                className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink sm:w-48"
                value={genre}
                onChange={(e) => resetPageAnd(setGenre)(e.target.value)}
                placeholder="Action, Drama…"
              />
            </label>
            <label className="block text-sm font-medium text-ink-dim">
              Genre tracker
              <select
                aria-label="Genre tracker"
                className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink sm:w-48"
                value={trackerGenre}
                onChange={(e) => resetPageAnd(setTrackerGenre)(e.target.value as "" | "anime" | "documentaire")}
              >
                <option value="">Tous</option>
                <option value="anime">Anime</option>
                <option value="documentaire">Documentaire</option>
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
                className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink sm:w-48"
                value={processed}
                onChange={(e) => resetPageAnd(setProcessed)(e.target.value as "" | "true" | "false")}
              >
                <option value="">Peu importe</option>
                <option value="true">Déjà traité</option>
                <option value="false">Jamais traité</option>
              </select>
            </label>
            {advancedFilterCount > 0 && (
              <Button
                variant="link-muted"
                className="pb-2 text-sm"
                onClick={() => {
                  setGenre("");
                  setTrackerGenre("");
                  setAddedSinceDays("");
                  setProcessed("");
                  setPage(1);
                }}
              >
                Effacer ces filtres
              </Button>
            )}
          </div>
        )}
      </div>

      {seasonPacks.length > 0 && (
        <InlineBanner>
          <button
            type="button"
            onClick={() => setPacksExpanded((v) => !v)}
            aria-expanded={packsExpanded}
            className="flex w-full items-center justify-between px-3 py-1.5 text-xs font-medium uppercase tracking-wide text-ink-dim hover:text-ink transition-colors duration-100 active:bg-line"
          >
            <span>
              {seasonPacks.length} pack{seasonPacks.length > 1 ? "s" : ""} disponible
              {seasonPacks.length > 1 ? "s" : ""}
            </span>
            <ChevronDown
              size={14}
              aria-hidden="true"
              className={`transition-transform duration-200 motion-reduce:transition-none ${packsExpanded ? "rotate-180" : ""}`}
            />
          </button>
          {packsExpanded && (
            <div className="max-h-64 overflow-y-auto">
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
                    className="flex items-center justify-between px-3 py-2 text-sm"
                  >
                    <span>
                      {pack.title} — {label} ({pack.team})
                    </span>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={seasons === null}
                      title={
                        seasons === null
                          ? "Certaines saisons de ce pack ne sont pas visibles dans la page/le filtre actuel."
                          : undefined
                      }
                      onClick={() => {
                        if (seasons === null) return;
                        openUpload({
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
                    >
                      Préparer le pack
                    </Button>
                  </div>
                );
              })}
            </div>
          )}
        </InlineBanner>
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
        // Conteneur defilant : 10 colonnes (dont plusieurs nowrap) ne tiennent
        // pas sous 768px -- sans lui, c'est toute la page qui s'elargit
        // (audit front 2026-10-14, meme patron que SeedQueuePage).
        <div className="overflow-x-auto rounded-md border border-line bg-surface">
          <table className="w-full text-sm">
            <thead className="bg-surface-2 text-left text-ink-dim">
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    header.column.id === "select" ? (
                      <th key={header.id} className="w-10 px-4 py-2">
                        <input
                          type="checkbox"
                          aria-label="Tout sélectionner (page)"
                          checked={pageSelection === "all"}
                          ref={(el) => {
                            if (el) el.indeterminate = pageSelection === "some";
                          }}
                          onChange={togglePageSelection}
                          className="h-4 w-4 rounded border-line-strong"
                        />
                      </th>
                    ) : (
                      <SortableHeader key={header.id} header={header} className="px-4 py-2" />
                    )
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
                        <TriangleAlert size={12} aria-hidden="true" className="mr-1 inline-block align-[-2px]" />
                        chemin
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
                    {/* Actions groupees et hierarchisees (audit front
                        2026-10-14, lot 6) : l'action principale en bouton,
                        les secondaires en liens, toutes alignees a droite. */}
                    <div className="flex items-center justify-end gap-3">
                      {item.path_resolved && item.local_paths.length > 0 && (
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() =>
                            openUpload({
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
                        >
                          Préparer l'upload
                        </Button>
                      )}
                      {item.seed_match && !seedMatchJobs[item.key] && (
                        <Button
                          variant="link"
                          onClick={() => handleStartSeedMatch(item)}
                          className="text-sm"
                        >
                          Seed possible
                        </Button>
                      )}
                      {seedMatchJobs[item.key]
                        && seedMatchJobs[item.key].state !== "done"
                        && seedMatchJobs[item.key].state !== "mismatch"
                        && seedMatchJobs[item.key].state !== "error" && (
                        <span className="text-xs text-ink-dim">
                          Vérification…
                          <Button
                            variant="link-danger"
                            onClick={() => handleCancelSeedMatch(item.key)}
                            className="ml-1"
                          >
                            Annuler
                          </Button>
                        </span>
                      )}
                      {seedMatchJobs[item.key]?.state === "done" && (
                        <span className="text-xs text-good">
                          <Check size={12} aria-hidden="true" className="mr-1 inline-block align-[-2px]" />
                          En seed
                        </span>
                      )}
                      {seedMatchJobs[item.key]?.state === "mismatch" && (
                        <span
                          className="ml-3 text-xs text-warn"
                          title={seedMatchJobs[item.key].result?.warning ?? undefined}
                        >
                          <TriangleAlert size={12} aria-hidden="true" className="mr-1 inline-block align-[-2px]" />
                          {seedMatchJobs[item.key].result?.warning}
                        </span>
                      )}
                      {seedMatchJobs[item.key]?.state === "error" && (
                        <span className="text-xs text-crit">
                          <TriangleAlert size={12} aria-hidden="true" className="mr-1 inline-block align-[-2px]" />
                          {seedMatchJobs[item.key].error}
                        </span>
                      )}
                      <Link to="/" className="text-sm text-ink-faint underline underline-offset-2 hover:text-ink">
                        Générer
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {items !== null && items.length > 0 && (
        <PaginationBar
          page={page} total={total} pageSize={PAGE_SIZE}
          onFirst={() => setPage(1)}
          onPrev={() => setPage((p) => Math.max(1, p - 1))}
          onNext={() => setPage((p) => (p * PAGE_SIZE < total ? p + 1 : p))}
        />
      )}

      {selected.size > 0 && (
        // Barre de selection contextuelle (audit front 2026-10-14, lot 6) :
        // n'existe que s'il y a une selection -- plus de bouton primaire
        // "Verifier (0 sélectionnés)" desactive en permanence. Materiau
        // translucide flottant (le tableau reste lisible dessous), plein
        // si le systeme demande moins de transparence.
        <div
          role="region"
          aria-label="Sélection"
          className="fixed inset-x-4 bottom-[calc(5rem+env(safe-area-inset-bottom))] z-30 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface/85 px-4 py-3 shadow-lg backdrop-blur-xl backdrop-saturate-150 transition-[translate,opacity] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] starting:translate-y-4 starting:opacity-0 motion-reduce:transition-opacity motion-reduce:starting:translate-y-0 reduced-transparency:bg-surface reduced-transparency:backdrop-blur-none md:inset-x-auto md:right-6 md:bottom-6 md:justify-start"
        >
          <span className="text-sm font-medium text-ink" aria-live="polite">
            {selected.size} sélectionné{selected.size > 1 ? "s" : ""}
          </span>
          <span className="flex flex-wrap items-center gap-2">
            <Button variant="primary" size="sm" onClick={handleVerifySelection} disabled={starting || running}>
              Vérifier sur le tracker
            </Button>
            <Button variant="secondary" size="sm" onClick={clearSelection} className="inline-flex items-center gap-1">
              <X size={14} aria-hidden="true" />
              Désélectionner
            </Button>
          </span>
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
          seasonPack={activeUpload.seasonPack}
          open={uploadOpen}
          onClose={() => setUploadOpen(false)}
          onPendingChange={setUploadPending}
          // Pas de demontage si un envoi attend : le bandeau "Reprendre"
          // rouvre ce meme panneau, etat intact.
          onExited={() => {
            if (!uploadPending) setActiveUpload(null);
          }}
        />
      )}
    </div>
  );
}
