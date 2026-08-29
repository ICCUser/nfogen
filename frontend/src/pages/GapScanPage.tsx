import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { KeyValueEditor } from "../components/ListEditor";
import UploadPrepPanel from "../components/UploadPrepPanel";
import {
  downloadBlob,
  gapscanConfig,
  gapscanConfigWrite,
  gapscanExportCsv,
  gapscanResults,
  gapscanRun,
  gapscanStatus,
} from "../api/client";
import { ApiError } from "../api/types";
import type { GapResult, GapscanConfig, GapscanConfigWrite, GapscanStatus, GapStatus } from "../api/types";

const STATUS_LABEL: Record<GapStatus, string> = {
  absent: "Absent de C411",
  quality_gap: "Qualité supérieure disponible",
  language_gap: "Langue manquante sur C411",
  covered: "Déjà couvert",
  error: "Non vérifié (erreur C411)",
};

const STATUS_BADGE_CLASS: Record<GapStatus, string> = {
  absent: "bg-info-bg text-info",
  quality_gap: "bg-warn-bg text-warn",
  language_gap: "bg-warn-bg text-warn",
  covered: "bg-surface-2 text-ink-faint",
  error: "bg-crit-bg text-crit",
};

const FILTERS: { value: GapStatus | ""; label: string }[] = [
  { value: "", label: "Tous les statuts" },
  { value: "absent", label: STATUS_LABEL.absent },
  { value: "quality_gap", label: STATUS_LABEL.quality_gap },
  { value: "language_gap", label: STATUS_LABEL.language_gap },
  { value: "covered", label: STATUS_LABEL.covered },
  { value: "error", label: STATUS_LABEL.error },
];

// Un seul menu combinant media_type + genre (retour utilisateur, 2026-08-28 :
// deux selects separes qui se combinent n'etaient pas intuitifs). Chaque
// option correspond directement a une categorie C411 reelle (voir
// GAPSCAN.md, "Filtre type/genre + pagination serveur").
type TypeGenreOption = {
  value: string;
  label: string;
  mediaType?: "movie" | "series";
  genre?: "anime" | "documentaire";
};

const TYPE_GENRE_OPTIONS: TypeGenreOption[] = [
  { value: "", label: "Tous les types" },
  { value: "movie", label: "Films", mediaType: "movie" },
  { value: "series", label: "Séries", mediaType: "series" },
  { value: "movie:anime", label: "Films d'animation", mediaType: "movie", genre: "anime" },
  { value: "series:anime", label: "Séries animées", mediaType: "series", genre: "anime" },
  { value: "movie:documentaire", label: "Documentaires (films)", mediaType: "movie", genre: "documentaire" },
  { value: "series:documentaire", label: "Documentaires (séries)", mediaType: "series", genre: "documentaire" },
];

function qualitySummary(q: GapResult["local_quality"]): string {
  const parts = [
    q.resolution ? `${q.resolution}p` : null,
    q.source,
    q.languages.length > 0 ? q.languages.join("+") : null,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : "—";
}

/** Page « Scan C411 » : compare la bibliothèque Sonarr/Radarr au catalogue
 * C411 pour repérer les candidats à l'upload (voir GAPSCAN.md). Poll
 * `/gapscan/status` pendant qu'un scan tourne, comme la génération vidéo
 * côté navigateur poll son propre état d'avancement. */
export default function GapScanPage() {
  const [config, setConfig] = useState<GapscanConfig | null>(null);
  const [status, setStatus] = useState<GapscanStatus | null>(null);
  const [results, setResults] = useState<GapResult[] | null>(null);
  const [filter, setFilter] = useState<GapStatus | "">("");
  const [typeGenreFilter, setTypeGenreFilter] = useState("");
  const selectedTypeGenre =
    TYPE_GENRE_OPTIONS.find((o) => o.value === typeGenreFilter) ?? TYPE_GENRE_OPTIONS[0];
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const PAGE_SIZE = 50;
  const [error, setError] = useState<string | null>(null);
  const [activeUpload, setActiveUpload] = useState<{ title: string; localPaths: string[] } | null>(null);
  const [starting, setStarting] = useState(false);
  // Scan rapide (mode incremental) : coche par defaut des qu'un scan
  // precedent existe (voir handleRun / GAPSCAN.md, "Persistance des
  // resultats + scan incremental") -- l'utilisateur peut decocher pour
  // forcer un scan complet.
  const [incremental, setIncremental] = useState(true);
  // Scan par categorie (retour utilisateur, 2026-08-27) : scanner Radarr et
  // Sonarr separement, pour repartir la charge sur plusieurs sessions
  // (limite C411 confirmee : 15 requetes/min).
  const [only, setOnly] = useState<"" | "movies" | "series">("");
  const pollRef = useRef<number | null>(null);

  // Formulaire de configuration (Sonarr/Radarr/C411) : replie par defaut,
  // deplie automatiquement une fois qu'on sait qu'il manque quelque chose
  // (voir l'effet plus bas, une fois `config` charge).
  const [showConfigForm, setShowConfigForm] = useState(false);
  const [configSaving, setConfigSaving] = useState(false);
  const [configSaved, setConfigSaved] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);
  const [sonarrUrl, setSonarrUrl] = useState("");
  const [sonarrApiKey, setSonarrApiKey] = useState("");
  const [radarrUrl, setRadarrUrl] = useState("");
  const [radarrApiKey, setRadarrApiKey] = useState("");
  const [c411ApiKey, setC411ApiKey] = useState("");
  const [c411BaseUrl, setC411BaseUrl] = useState("");
  const [sonarrPathMappings, setSonarrPathMappings] = useState<Record<string, string>>({});
  const [radarrPathMappings, setRadarrPathMappings] = useState<Record<string, string>>({});
  const [c411AnnounceUrl, setC411AnnounceUrl] = useState("");
  const [stagingDir, setStagingDir] = useState("");

  useEffect(() => {
    gapscanConfig()
      .catch(() => null)
      .then((c) => {
        if (!c) return;
        setConfig(c);
        setSonarrUrl(c.sonarr_url ?? "");
        setRadarrUrl(c.radarr_url ?? "");
        setC411BaseUrl(c.c411_base_url ?? "");
        setSonarrPathMappings(c.sonarr_path_mappings);
        setRadarrPathMappings(c.radarr_path_mappings);
        setStagingDir(c.staging_dir ?? "");
        if (!c.c411_configured || (!c.sonarr_configured && !c.radarr_configured)) {
          setShowConfigForm(true);
        }
      });
    refreshStatus();
    return () => stopPolling();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Charge aussi au montage (tous les filtres valent "" et page=1 au
  // premier rendu) : un seul useEffect dedie au montage appellerait
  // loadResults() une seconde fois en double de celui-ci, cf. historique
  // du fichier.
  useEffect(() => {
    loadResults();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter, typeGenreFilter, page]);

  // setFilter/setPage groupes dans le meme gestionnaire d'evenement :
  // React les applique en un seul rendu, donc un seul appel a loadResults
  // (pas de fetch intermediaire sur l'ancienne page avec le nouveau
  // filtre).
  function handleFilterChange(next: GapStatus | "") {
    setFilter(next);
    setPage(1);
  }

  function handleTypeGenreChange(next: string) {
    setTypeGenreFilter(next);
    setPage(1);
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
        loadResults();
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

  async function loadResults() {
    try {
      const res = await gapscanResults({
        status: filter || undefined,
        mediaType: selectedTypeGenre.mediaType,
        genre: selectedTypeGenre.genre,
        page,
        pageSize: PAGE_SIZE,
      });
      setResults(res.items);
      setTotal(res.total);
    } catch (e) {
      setResults(null);
      setTotal(0);
      setError(e instanceof ApiError ? e.message : "Résultats indisponibles.");
    }
  }

  async function handleRun() {
    setStarting(true);
    setError(null);
    try {
      await gapscanRun(hasPreviousScan && incremental, only || undefined);
      // refreshStatus() demarre elle-meme le polling si l'etat est
      // "running" (voir plus haut) -- pas d'appel a startPolling() ici :
      // un scan deja termine au premier appel ne doit pas en declencher un
      // inutilement.
      const s = await refreshStatus();
      if (s && s.state !== "running") loadResults();
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
      if (c411ApiKey.trim()) fields.c411_api_key = c411ApiKey.trim();
      if (c411BaseUrl.trim()) fields.c411_base_url = c411BaseUrl.trim();
      if (c411AnnounceUrl.trim()) fields.c411_announce_url = c411AnnounceUrl.trim();
      if (stagingDir.trim()) fields.staging_dir = stagingDir.trim();
      // Contrairement aux cles/URLs ci-dessus, un dictionnaire vide est une
      // valeur explicite valide ("aucun mapping") : toujours envoye.
      fields.sonarr_path_mappings = sonarrPathMappings;
      fields.radarr_path_mappings = radarrPathMappings;

      const updated = await gapscanConfigWrite(fields);
      setConfig(updated);
      setSonarrApiKey("");
      setRadarrApiKey("");
      setC411ApiKey("");
      setC411AnnounceUrl("");
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
        status: filter || undefined,
        mediaType: selectedTypeGenre.mediaType,
        genre: selectedTypeGenre.genre,
      });
      downloadBlob(blob, "gapscan.csv");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Export impossible.");
    }
  }

  const running = status?.state === "running";
  const notConfigured = config !== null && !config.c411_configured;
  const noLibrary = config !== null && config.c411_configured && !config.sonarr_configured && !config.radarr_configured;
  // Un scan precedent existe (memoire ou repris du disque au demarrage,
  // voir gapscan_results_store.py) des qu'un "done" a deja ete rapporte.
  const hasPreviousScan = status?.state === "done" && status.finished_at !== null;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-xl font-semibold text-ink">Scan C411</h1>
          <p className="text-sm text-ink-dim">
            Compare ta bibliothèque Sonarr/Radarr au catalogue C411 pour repérer ce qui n'y est pas
            encore, ou pas dans ta qualité — candidats à uploader.
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
            <label className="flex items-center gap-1.5 text-sm text-ink-dim" title="Reprend les titres déjà couverts et inchangés du dernier scan sans les réinterroger sur C411 — plus rapide.">
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
            disabled={!results || results.length === 0}
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
            {running ? "Scan en cours…" : "Lancer un scan"}
          </button>
        </div>
      </div>

      {notConfigured && (
        <div className="rounded-md border border-warn bg-warn-bg px-4 py-3 text-sm text-warn">
          Clé API C411 non configurée — renseigne-la ci-dessous.
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
          Configuration (Sonarr, Radarr, C411)
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
                URL de base C411
                <input
                  className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                  placeholder="https://c411.org"
                  value={c411BaseUrl}
                  onChange={(e) => setC411BaseUrl(e.target.value)}
                />
              </label>
              <label className="block text-sm font-medium text-ink-dim">
                Clé API C411
                <input
                  className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                  type="password"
                  placeholder={config?.c411_configured ? "•••• (enregistrée)" : ""}
                  value={c411ApiKey}
                  onChange={(e) => setC411ApiKey(e.target.value)}
                />
              </label>
              <label className="block text-sm font-medium text-ink-dim">
                Adresse d'annonce C411
                <input
                  className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink font-mono"
                  type="password"
                  placeholder={config?.c411_announce_url_configured ? "•••• (enregistrée)" : ""}
                  value={c411AnnounceUrl}
                  onChange={(e) => setC411AnnounceUrl(e.target.value)}
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

      <div className="flex flex-wrap items-end gap-3">
        <label className="block text-sm font-medium text-ink-dim">
          Filtrer par statut
          <select
            className="mt-1 w-full max-w-xs rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={filter}
            onChange={(e) => handleFilterChange(e.target.value as GapStatus | "")}
          >
            {FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm font-medium text-ink-dim">
          Type
          <select
            aria-label="Type"
            className="mt-1 w-full max-w-xs rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={typeGenreFilter}
            onChange={(e) => handleTypeGenreChange(e.target.value)}
          >
            {TYPE_GENRE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {results === null && !error && <p className="text-sm text-ink-faint">Chargement…</p>}

      {results !== null && results.length === 0 && (
        <p className="text-sm text-ink-faint">
          Aucun résultat{filter && " pour ce statut"}. {!status || status.state === "idle" ? "Lance un scan pour commencer." : ""}
        </p>
      )}

      {results !== null && results.length > 0 && (
        <table className="w-full overflow-hidden rounded-md border border-line bg-surface text-sm">
          <thead className="bg-surface-2 text-left text-ink-dim">
            <tr>
              <th className="px-4 py-2">Titre</th>
              <th className="px-4 py-2">Type</th>
              <th className="px-4 py-2">Statut</th>
              <th className="px-4 py-2">Ta version</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody>
            {results.map((r, i) => (
              <tr key={`${r.imdb_id ?? r.tvdb_id ?? r.title}-${r.season_number ?? i}`} className="border-t border-line">
                <td className="px-4 py-2 font-mono font-medium text-ink">
                  {r.title} {r.year ? `(${r.year})` : ""}
                  {!r.path_resolved && (
                    <span
                      className="ml-1 rounded-full bg-warn-bg px-2 py-0.5 text-xs text-warn"
                      title={r.path_error ?? "Chemin local non résolu"}
                    >
                      ⚠ chemin
                    </span>
                  )}
                </td>
                <td className="px-4 py-2 text-ink-dim">
                  {r.media_type === "movie" ? "Film" : `Série S${String(r.season_number).padStart(2, "0")}`}
                </td>
                <td className="whitespace-nowrap px-4 py-2">
                  <span
                    className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs ${STATUS_BADGE_CLASS[r.status]}`}
                    title={r.status === "error" ? r.error ?? undefined : undefined}
                  >
                    {STATUS_LABEL[r.status]}
                  </span>
                  {r.has_freeleech_alternative && (
                    <span className="ml-1 rounded-full bg-good-bg px-2 py-0.5 text-xs text-good">FL</span>
                  )}
                  {r.has_double_upload_window && (
                    <span className="ml-1 rounded-full bg-info-bg px-2 py-0.5 text-xs text-info">2x</span>
                  )}
                </td>
                <td className="whitespace-nowrap px-4 py-2 font-mono text-ink-dim">
                  {qualitySummary(r.local_quality)}
                </td>
                <td className="whitespace-nowrap px-4 py-2 text-right">
                  <Link to="/" className="text-sm text-accent-ink underline">
                    Générer
                  </Link>
                  {r.path_resolved && r.local_paths.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setActiveUpload({ title: r.title, localPaths: r.local_paths })}
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
          onClose={() => setActiveUpload(null)}
        />
      )}
    </div>
  );
}
