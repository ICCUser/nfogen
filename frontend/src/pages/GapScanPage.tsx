import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
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
import type { GapResult, GapscanConfig, GapscanStatus, GapStatus } from "../api/types";

const STATUS_LABEL: Record<GapStatus, string> = {
  absent: "Absent de C411",
  quality_gap: "Qualité supérieure disponible",
  language_gap: "Langue manquante sur C411",
  covered: "Déjà couvert",
};

const STATUS_BADGE_CLASS: Record<GapStatus, string> = {
  absent: "bg-sky-100 text-sky-700",
  quality_gap: "bg-amber-100 text-amber-800",
  language_gap: "bg-amber-100 text-amber-800",
  covered: "bg-slate-100 text-slate-500",
};

const FILTERS: { value: GapStatus | ""; label: string }[] = [
  { value: "", label: "Tous les statuts" },
  { value: "absent", label: STATUS_LABEL.absent },
  { value: "quality_gap", label: STATUS_LABEL.quality_gap },
  { value: "language_gap", label: STATUS_LABEL.language_gap },
  { value: "covered", label: STATUS_LABEL.covered },
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
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
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

  useEffect(() => {
    gapscanConfig()
      .catch(() => null)
      .then((c) => {
        if (!c) return;
        setConfig(c);
        setSonarrUrl(c.sonarr_url ?? "");
        setRadarrUrl(c.radarr_url ?? "");
        setC411BaseUrl(c.c411_base_url ?? "");
        if (!c.c411_configured || (!c.sonarr_configured && !c.radarr_configured)) {
          setShowConfigForm(true);
        }
      });
    refreshStatus();
    return () => stopPolling();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Charge aussi au montage (filter vaut "" au premier rendu) : un seul
  // useEffect dedie au montage appellerait loadResults() une seconde fois
  // en double de celui-ci, cf. historique du fichier.
  useEffect(() => {
    loadResults();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

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
      setResults(await gapscanResults(filter || undefined));
    } catch (e) {
      setResults(null);
      setError(e instanceof ApiError ? e.message : "Résultats indisponibles.");
    }
  }

  async function handleRun() {
    setStarting(true);
    setError(null);
    try {
      await gapscanRun();
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
      const fields: Record<string, string> = {};
      if (sonarrUrl.trim()) fields.sonarr_url = sonarrUrl.trim();
      if (sonarrApiKey.trim()) fields.sonarr_api_key = sonarrApiKey.trim();
      if (radarrUrl.trim()) fields.radarr_url = radarrUrl.trim();
      if (radarrApiKey.trim()) fields.radarr_api_key = radarrApiKey.trim();
      if (c411ApiKey.trim()) fields.c411_api_key = c411ApiKey.trim();
      if (c411BaseUrl.trim()) fields.c411_base_url = c411BaseUrl.trim();

      const updated = await gapscanConfigWrite(fields);
      setConfig(updated);
      setSonarrApiKey("");
      setRadarrApiKey("");
      setC411ApiKey("");
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
      const blob = await gapscanExportCsv(filter || undefined);
      downloadBlob(blob, "gapscan.csv");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Export impossible.");
    }
  }

  const running = status?.state === "running";
  const notConfigured = config !== null && !config.c411_configured;
  const noLibrary = config !== null && config.c411_configured && !config.sonarr_configured && !config.radarr_configured;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Scan C411</h1>
          <p className="text-sm text-slate-600">
            Compare ta bibliothèque Sonarr/Radarr au catalogue C411 pour repérer ce qui n'y est pas
            encore, ou pas dans ta qualité — candidats à uploader.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={handleExportCsv}
            disabled={!results || results.length === 0}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm hover:bg-slate-100 disabled:opacity-50"
          >
            Export CSV
          </button>
          <button
            type="button"
            onClick={handleRun}
            disabled={starting || running || notConfigured || noLibrary}
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            {running ? "Scan en cours…" : "Lancer un scan"}
          </button>
        </div>
      </div>

      {notConfigured && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Clé API C411 non configurée — renseigne-la ci-dessous.
        </div>
      )}
      {!notConfigured && noLibrary && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Aucune instance Sonarr ni Radarr configurée — renseigne au moins l'une des deux ci-dessous.
        </div>
      )}

      <div className="rounded-md border border-slate-200 bg-white">
        <button
          type="button"
          onClick={() => setShowConfigForm((v) => !v)}
          className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium text-slate-900"
        >
          Configuration (Sonarr, Radarr, C411)
          <span className="text-slate-400">{showConfigForm ? "▲" : "▼"}</span>
        </button>
        {showConfigForm && (
          <div className="space-y-3 border-t border-slate-200 p-4">
            <p className="text-xs text-slate-500">
              Enregistré côté serveur ({" "}
              <code className="rounded bg-slate-100 px-1">NFOGEN_GAPSCAN_CONFIG_FILE</code>{" "}
              requis). Un champ « clé » laissé vide ne modifie pas la clé déjà enregistrée.
            </p>

            <div className="grid grid-cols-2 gap-3">
              <label className="block text-sm font-medium text-slate-700">
                URL Sonarr
                <input
                  className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  placeholder="http://sonarr.local:8989"
                  value={sonarrUrl}
                  onChange={(e) => setSonarrUrl(e.target.value)}
                />
              </label>
              <label className="block text-sm font-medium text-slate-700">
                Clé API Sonarr
                <input
                  className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  type="password"
                  placeholder={config?.sonarr_configured ? "•••• (enregistrée)" : ""}
                  value={sonarrApiKey}
                  onChange={(e) => setSonarrApiKey(e.target.value)}
                />
              </label>
              <label className="block text-sm font-medium text-slate-700">
                URL Radarr
                <input
                  className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  placeholder="http://radarr.local:7878"
                  value={radarrUrl}
                  onChange={(e) => setRadarrUrl(e.target.value)}
                />
              </label>
              <label className="block text-sm font-medium text-slate-700">
                Clé API Radarr
                <input
                  className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  type="password"
                  placeholder={config?.radarr_configured ? "•••• (enregistrée)" : ""}
                  value={radarrApiKey}
                  onChange={(e) => setRadarrApiKey(e.target.value)}
                />
              </label>
              <label className="block text-sm font-medium text-slate-700">
                URL de base C411
                <input
                  className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  placeholder="https://c411.org"
                  value={c411BaseUrl}
                  onChange={(e) => setC411BaseUrl(e.target.value)}
                />
              </label>
              <label className="block text-sm font-medium text-slate-700">
                Clé API C411
                <input
                  className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  type="password"
                  placeholder={config?.c411_configured ? "•••• (enregistrée)" : ""}
                  value={c411ApiKey}
                  onChange={(e) => setC411ApiKey(e.target.value)}
                />
              </label>
            </div>

            {configError && <p className="text-sm text-red-600">{configError}</p>}

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={handleSaveConfig}
                disabled={configSaving}
                className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
              >
                {configSaving ? "Enregistrement…" : "Enregistrer"}
              </button>
              {configSaved && <span className="text-sm text-emerald-600">Enregistré.</span>}
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error} — vérifiez les <Link to="/settings" className="underline">réglages de connexion</Link>.
        </div>
      )}

      {status && status.state === "error" && status.error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Le dernier scan a échoué : {status.error}
        </div>
      )}

      {running && (
        <div className="space-y-1 rounded-md border border-slate-200 bg-white p-4">
          <p className="text-sm text-slate-600">
            {status && status.total > 0
              ? `${status.processed} / ${status.total} titres traités…`
              : "Récupération de la bibliothèque…"}
          </p>
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full bg-slate-900 transition-all"
              style={{
                width: status && status.total > 0 ? `${(100 * status.processed) / status.total}%` : "10%",
              }}
            />
          </div>
        </div>
      )}

      <label className="block text-sm font-medium text-slate-700">
        Filtrer par statut
        <select
          className="mt-1 w-full max-w-xs rounded-md border border-slate-300 px-3 py-2 text-sm"
          value={filter}
          onChange={(e) => setFilter(e.target.value as GapStatus | "")}
        >
          {FILTERS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>
      </label>

      {results === null && !error && <p className="text-sm text-slate-500">Chargement…</p>}

      {results !== null && results.length === 0 && (
        <p className="text-sm text-slate-500">
          Aucun résultat{filter && " pour ce statut"}. {!status || status.state === "idle" ? "Lance un scan pour commencer." : ""}
        </p>
      )}

      {results !== null && results.length > 0 && (
        <table className="w-full overflow-hidden rounded-md border border-slate-200 bg-white text-sm">
          <thead className="bg-slate-100 text-left text-slate-600">
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
              <tr key={`${r.imdb_id ?? r.tvdb_id ?? r.title}-${r.season_number ?? i}`} className="border-t border-slate-100">
                <td className="px-4 py-2 font-medium text-slate-900">
                  {r.title} {r.year ? `(${r.year})` : ""}
                </td>
                <td className="px-4 py-2 text-slate-600">
                  {r.media_type === "movie" ? "Film" : `Série S${String(r.season_number).padStart(2, "0")}`}
                </td>
                <td className="px-4 py-2">
                  <span className={`rounded-full px-2 py-0.5 text-xs ${STATUS_BADGE_CLASS[r.status]}`}>
                    {STATUS_LABEL[r.status]}
                  </span>
                  {r.has_freeleech_alternative && (
                    <span className="ml-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-700">FL</span>
                  )}
                  {r.has_double_upload_window && (
                    <span className="ml-1 rounded-full bg-indigo-100 px-2 py-0.5 text-xs text-indigo-700">2x</span>
                  )}
                </td>
                <td className="px-4 py-2 text-slate-600">{qualitySummary(r.local_quality)}</td>
                <td className="px-4 py-2 text-right">
                  <Link to="/" className="text-sm text-slate-700 underline">
                    Générer
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
