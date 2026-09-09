import { useEffect, useRef, useState } from "react";
import {
  cancelCommitJob,
  cancelIntegrityJob,
  cancelUploadPreviewJob,
  commitJobStatus,
  integrityJobStatus,
  prepareUploadCommit,
  prepareUploadPreview,
  sendToTracker,
  uploadPreviewJobStatus,
  verifyIntegrity,
} from "../api/client";
import { ApiError } from "../api/types";
import type {
  CommitJob,
  IntegrityJob,
  SeasonPackRequest,
  SendToTrackerResult,
  UploadCommitResult,
  UploadGroupProposal,
  UploadPreviewJob,
} from "../api/types";
import { useProfile } from "../ProfileContext";

const STEP_LABELS: Record<string, string> = {
  staging: "Mise en scène",
  generating_nfo: "Génération du .nfo",
  building_torrent: "Génération du torrent",
};

const TERMINAL_STATES = ["done", "error", "cancelled"];

/** Apercu (sans ecriture disque) puis confirmation par groupe de la mise
 * en scene + generation de .torrent (AUTOMATION.md, sous-projet 4). Un
 * groupe = un tag d'equipe detecte -- un pack assemble depuis plusieurs
 * releases devient plusieurs groupes independants (voir
 * nfogen/upload_prep.py:group_by_team). Jamais de "tout confirmer" :
 * chaque groupe se confirme individuellement, coherent avec la decision
 * "upload un par un" (AUTOMATION.md, "Decisions deja prises").
 *
 * "Confirmer" demarre une tache de fond suivie en polling (AUTOMATION.md,
 * sous-projet 4c) -- une mise en scene par copie (volumes differents) ou
 * un hachage de torrent peuvent prendre plusieurs minutes, jamais bloquer
 * la page pendant ce temps. */
export default function UploadPrepPanel({
  localPaths,
  title,
  mediaType,
  radarrMovieId,
  sonarrSeriesId,
  tmdbId,
  tvdbId,
  genre,
  seasonNumber,
  seasonPack,
  onClose,
}: {
  localPaths: string[];
  title: string;
  mediaType: "movie" | "series";
  radarrMovieId: number | null;
  sonarrSeriesId: number | null;
  tmdbId: number | null;
  tvdbId: number | null;
  genre: "anime" | "documentaire" | null;
  seasonNumber: number | null;
  /** Pack de saisons fusionnees (bouton "Preparer le pack", Bibliotheque) --
   * quand fourni, ignore localPaths cote backend et construit un seul
   * groupe multi-saisons (voir nfogen/upload_prep.py:_preview_season_pack). */
  seasonPack?: SeasonPackRequest;
  onClose: () => void;
}) {
  const { profile: globalProfile, profiles } = useProfile();
  const [profile, setProfile] = useState(globalProfile);
  const [groups, setGroups] = useState<UploadGroupProposal[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [recalculating, setRecalculating] = useState(false);
  // Calcul de l'apercu EN TACHE DE FOND (retour utilisateur, 2026-09-09 :
  // "j'ai le film Bernie qui est ultra long [...] juste Calcul de
  // l'apercu [...] je me suis fait avoir") -- un fichier sans debit/
  // frequence d'image deja indiques dans ses metadonnees peut forcer une
  // analyse bien plus longue. previewJob porte la progression reelle
  // (utile surtout pour un pack) ET permet d'annuler.
  const [previewJob, setPreviewJob] = useState<UploadPreviewJob | null>(null);
  const [titleOverride, setTitleOverride] = useState(title);
  const [commitJobs, setCommitJobs] = useState<Record<number, CommitJob>>({});
  const [commitResults, setCommitResults] = useState<Record<number, UploadCommitResult>>({});
  const [commitErrors, setCommitErrors] = useState<Record<number, string>>({});
  const [sending, setSending] = useState<{ index: number; direct: boolean } | null>(null);
  // Quel mode a produit sendResults[index] -- distingue "Brouillon créé"
  // de "Uploadé directement" a l'affichage (voir handleSend).
  const [sentDirect, setSentDirect] = useState<Record<number, boolean>>({});
  const [sendResults, setSendResults] = useState<Record<number, SendToTrackerResult>>({});
  const [sendErrors, setSendErrors] = useState<Record<number, string>>({});
  // Verification d'integrite AVANT un upload direct (AUTOMATION.md,
  // sous-projet 7) -- jamais pour un brouillon. Cle : par index de
  // groupe, comme les autres etats de ce composant.
  const [integrityJobs, setIntegrityJobs] = useState<Record<number, IntegrityJob>>({});
  const [integrityErrors, setIntegrityErrors] = useState<Record<number, string>>({});
  const pollRefs = useRef<Record<number, number>>({});

  async function pollPreviewUntilTerminal(jobId: string): Promise<UploadPreviewJob> {
    for (;;) {
      const job = await uploadPreviewJobStatus(jobId);
      setPreviewJob(job);
      if (TERMINAL_STATES.includes(job.state)) return job;
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
    }
  }

  async function loadPreview(override?: string, profileOverride: string = profile) {
    setRecalculating(true);
    setLoadError(null);
    setGroups(null);
    setPreviewJob(null);
    try {
      const { job_id } = await prepareUploadPreview(localPaths, profileOverride, override || undefined, seasonPack);
      const job = await pollPreviewUntilTerminal(job_id);
      if (job.state === "done") {
        setGroups(job.result ?? []);
      } else if (job.state === "cancelled") {
        setLoadError("Aperçu annulé.");
      } else {
        setLoadError(job.error ?? "Aperçu indisponible.");
      }
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : "Aperçu indisponible.");
    } finally {
      setRecalculating(false);
    }
  }

  async function handleCancelPreview() {
    if (!previewJob) return;
    try {
      await cancelUploadPreviewJob(previewJob.job_id);
    } catch {
      // best effort -- le prochain poll reflete l'etat reel de toute facon
    }
  }

  useEffect(() => {
    loadPreview(title);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [localPaths]);

  useEffect(() => {
    return () => {
      Object.values(pollRefs.current).forEach((id) => window.clearInterval(id));
    };
  }, []);

  function handleProfileChange(next: string) {
    setProfile(next);
    loadPreview(titleOverride, next);
  }

  function stopPolling(index: number) {
    const id = pollRefs.current[index];
    if (id !== undefined) {
      window.clearInterval(id);
      delete pollRefs.current[index];
    }
  }

  async function pollCommitJob(index: number, jobId: string) {
    try {
      const job = await commitJobStatus(jobId);
      setCommitJobs((prev) => ({ ...prev, [index]: job }));
      if (!TERMINAL_STATES.includes(job.state)) return;
      stopPolling(index);
      setCommitJobs((prev) => {
        const next = { ...prev };
        delete next[index];
        return next;
      });
      if (job.state === "done" && job.result) {
        setCommitResults((prev) => ({ ...prev, [index]: job.result as UploadCommitResult }));
      } else if (job.state === "error") {
        setCommitErrors((prev) => ({ ...prev, [index]: job.error ?? "Confirmation impossible." }));
      } else {
        setCommitErrors((prev) => ({ ...prev, [index]: "Annulé." }));
      }
    } catch (e) {
      stopPolling(index);
      setCommitErrors((prev) => ({
        ...prev,
        [index]: e instanceof ApiError ? e.message : "Suivi de la tâche impossible.",
      }));
    }
  }

  async function handleConfirm(index: number, group: UploadGroupProposal) {
    if (!group.release_name) return;
    setCommitErrors((prev) => ({ ...prev, [index]: "" }));
    try {
      const { job_id } = await prepareUploadCommit(group.release_name, group.files, profile, {
        mediaType,
        radarrMovieId: radarrMovieId ?? undefined,
        sonarrSeriesId: sonarrSeriesId ?? undefined,
        seasonNumber: seasonNumber ?? undefined,
      });
      // L'intervalle est enregistre AVANT le premier appel : si ce premier
      // appel atteint deja un etat terminal (job termine tres vite), son
      // propre stopPolling() doit pouvoir le retrouver et l'annuler.
      pollRefs.current[index] = window.setInterval(() => pollCommitJob(index, job_id), 1500);
      await pollCommitJob(index, job_id);
    } catch (e) {
      setCommitErrors((prev) => ({
        ...prev,
        [index]: e instanceof ApiError ? e.message : "Confirmation impossible.",
      }));
    }
  }

  async function handleCancel(index: number) {
    const job = commitJobs[index];
    if (!job) return;
    try {
      await cancelCommitJob(job.job_id);
    } catch {
      // best effort -- le prochain polling reflete l'etat reel de toute facon
    }
  }

  async function pollIntegrityUntilTerminal(index: number, jobId: string): Promise<IntegrityJob> {
    for (;;) {
      const job = await integrityJobStatus(jobId);
      setIntegrityJobs((prev) => ({ ...prev, [index]: job }));
      if (TERMINAL_STATES.includes(job.state)) return job;
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
    }
  }

  async function handleCancelIntegrity(index: number) {
    const job = integrityJobs[index];
    if (!job) return;
    try {
      await cancelIntegrityJob(job.job_id);
    } catch {
      // best effort -- le prochain poll reflete l'etat reel de toute facon
    }
  }

  // Un groupe deja "Confirmer" (fichier/torrent/nfo ecrits) mais pas
  // encore envoye (brouillon ou direct) -- fermer sans avertir perdrait
  // l'acces au bouton d'envoi (rien n'est supprime cote serveur, voir
  // handleRequestClose, mais il faudrait rouvrir le panneau pour le
  // retrouver).
  const hasUnsentProgress = Boolean(groups?.some((_, index) => commitResults[index] && !sendResults[index]));

  function handleRequestClose() {
    if (
      hasUnsentProgress &&
      !confirm(
        "Un groupe est prêt (mise en scène + .torrent faits) mais pas encore envoyé — " +
          "fermer maintenant ? Rien n'est perdu côté serveur, mais il faudra rouvrir ce " +
          "panneau pour créer le brouillon ou uploader.",
      )
    ) {
      return;
    }
    onClose();
  }

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") handleRequestClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasUnsentProgress]);

  async function handleSend(index: number, direct: boolean) {
    const commit = commitResults[index];
    if (!commit) return;
    // Upload direct : part reellement en moderation (POST /api/torrents,
    // retour d'un membre de l'equipe C411, 2026-09-07) -- une derniere
    // confirmation, contrairement au brouillon qui reste toujours privé.
    if (direct && !confirm("Uploader directement sur C411 (hors brouillon) ? Ça part réellement en modération.")) {
      return;
    }
    setSending({ index, direct });
    setSendErrors((prev) => ({ ...prev, [index]: "" }));
    setIntegrityErrors((prev) => ({ ...prev, [index]: "" }));
    try {
      // Verification approfondie (AUTOMATION.md, sous-projet 7) --
      // UNIQUEMENT pour un upload direct, jamais un brouillon (qui reste
      // toujours privé tant que l'utilisateur ne le finalise pas
      // lui-meme sur le site).
      if (direct) {
        const { job_id } = await verifyIntegrity(commit.staged_path);
        const job = await pollIntegrityUntilTerminal(index, job_id);
        setIntegrityJobs((prev) => {
          const next = { ...prev };
          delete next[index];
          return next;
        });
        if (job.state !== "done" || !job.result?.passed) {
          const message =
            job.state === "cancelled"
              ? null
              : job.state === "error"
                ? (job.error ?? "Vérification impossible.")
                : (job.result?.errors.join(" ") ?? "Vérification échouée.");
          if (message) {
            setIntegrityErrors((prev) => ({ ...prev, [index]: message }));
          }
          return;
        }
      }
      const result = await sendToTracker({
        releaseName: commit.release_name,
        stagedPath: commit.staged_path,
        torrentPath: commit.torrent_path,
        nfoPath: commit.nfo_path,
        profile,
        mediaType,
        radarrMovieId: radarrMovieId ?? undefined,
        sonarrSeriesId: sonarrSeriesId ?? undefined,
        tmdbId: tmdbId ?? undefined,
        tvdbId: tvdbId ?? undefined,
        genre: genre ?? undefined,
        seasonNumber: seasonNumber ?? undefined,
        draftId: direct ? undefined : sendResults[index]?.draft_id,
        direct,
      });
      setSendResults((prev) => ({ ...prev, [index]: result }));
      setSentDirect((prev) => ({ ...prev, [index]: direct }));
    } catch (e) {
      setSendErrors((prev) => ({
        ...prev,
        [index]: e instanceof ApiError ? e.message : "Envoi impossible.",
      }));
    } finally {
      setSending(null);
    }
  }

  return (
    // Modale (retour utilisateur, 2026-09-09 : "c'est etonnamant pas
    // logique de tous mettre en bas de la page") -- toujours au meme
    // endroit a l'ecran, quelle que soit la ligne cliquee ou le
    // defilement de la Bibliotheque. Le clic sur le fond ferme (avec le
    // meme garde-fou que le bouton Fermer/Echap) ; un clic a l'interieur
    // de la boite ne doit jamais se propager jusqu'au fond.
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/50 p-4 sm:items-center"
      onClick={handleRequestClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Préparer l'upload — ${title}`}
        onClick={(e) => e.stopPropagation()}
        className="max-h-[90vh] w-full max-w-2xl space-y-3 overflow-y-auto rounded-md border border-line bg-surface p-4 shadow-lg"
      >
        <div className="flex items-center justify-between">
          <h2 className="font-display text-sm font-semibold text-ink">Préparer l'upload — {title}</h2>
          <button type="button" onClick={handleRequestClose} className="text-sm text-ink-faint hover:text-ink">
            Fermer
          </button>
        </div>

      <div className="flex items-end gap-2">
        <label className="block text-xs font-medium text-ink-dim">
          Profil pour cet upload
          <select
            aria-label="Profil pour cet upload"
            className="mt-1 w-full max-w-[10rem] rounded-md border border-line-strong bg-surface px-2 py-1.5 text-sm text-ink"
            value={profile}
            onChange={(e) => handleProfileChange(e.target.value)}
          >
            {Object.keys(profiles).length === 0 && <option value="c411">c411</option>}
            {Object.keys(profiles).map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label className="block flex-1 text-xs font-medium text-ink-dim">
          Titre (si différent de celui déduit du nom de fichier)
          <input
            className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-1.5 text-sm text-ink font-mono"
            placeholder="Laisser vide pour garder le titre déduit du nom de fichier"
            value={titleOverride}
            onChange={(e) => setTitleOverride(e.target.value)}
          />
        </label>
        <button
          type="button"
          onClick={() => loadPreview(titleOverride)}
          disabled={recalculating}
          className="rounded-md border border-line-strong px-3 py-1.5 text-xs text-ink hover:bg-surface-2 disabled:opacity-50"
        >
          {recalculating ? "Calcul…" : "Recalculer"}
        </button>
      </div>

      {loadError && <p className="text-sm text-crit">{loadError}</p>}
      {!groups && !loadError && (
        <div className="space-y-1 text-sm text-ink-faint">
          <p>
            {previewJob && previewJob.total > 1
              ? `Analyse en cours… (${previewJob.processed}/${previewJob.total} fichiers)`
              : "Analyse en cours…"}
          </p>
          <p className="text-xs">
            Un fichier dont le débit/la fréquence d'image ne sont pas déjà indiqués dans ses métadonnées
            peut nécessiter une analyse plus longue (surtout sur un stockage distant).
          </p>
          {previewJob && !TERMINAL_STATES.includes(previewJob.state) && (
            <button
              type="button"
              onClick={handleCancelPreview}
              className="text-xs text-crit underline hover:opacity-80"
            >
              Annuler
            </button>
          )}
        </div>
      )}

      {groups && groups.length === 0 && (
        <p className="text-sm text-ink-faint">Aucun fichier à préparer.</p>
      )}

      {groups?.map((group, index) => (
        <div key={index} className="space-y-2 rounded-md border border-line-strong p-3">
          <p className="font-mono text-sm font-medium text-ink">
            {group.release_name ?? "(nom impossible à calculer)"}
          </p>
          <ul className="space-y-0.5 text-xs text-ink-dim">
            {group.files.map((f) => (
              <li key={f.source_path} className="font-mono">
                {f.source_path.split(/[/\\]/).pop()} → {f.staged_name}
              </li>
            ))}
          </ul>
          {group.warnings.length > 0 && (
            <ul className="space-y-0.5 text-xs text-warn">
              {group.warnings.map((w, i) => (
                <li key={i}>⚠ {w}</li>
              ))}
            </ul>
          )}

          {!group.blocked && group.release_name && !commitResults[index] && !commitJobs[index] && (
            <button
              type="button"
              onClick={() => handleConfirm(index, group)}
              className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-surface hover:opacity-90 disabled:opacity-50"
            >
              Confirmer
            </button>
          )}
          {commitJobs[index] && (
            <div className="space-y-1">
              <div className="h-2 w-full overflow-hidden rounded bg-surface-2">
                <div
                  className="h-full bg-accent transition-all"
                  style={{ width: `${commitJobs[index].percent}%` }}
                />
              </div>
              <div className="flex items-center justify-between text-xs text-ink-dim">
                <span>
                  {STEP_LABELS[commitJobs[index].state] ?? commitJobs[index].state} —{" "}
                  {Math.round(commitJobs[index].percent)}%
                </span>
                <button type="button" onClick={() => handleCancel(index)} className="text-crit underline">
                  Annuler
                </button>
              </div>
            </div>
          )}
          {commitErrors[index] && <p className="text-xs text-crit">{commitErrors[index]}</p>}
          {commitResults[index] && (
            <p className="text-xs text-good">
              Mis en scène : <span className="font-mono">{commitResults[index].staged_path}</span>
              <br />
              Torrent : <span className="font-mono">{commitResults[index].torrent_path}</span>
              <br />
              NFO : <span className="font-mono">{commitResults[index].nfo_path}</span>
            </p>
          )}
          {commitResults[index] && !sendResults[index] && (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => handleSend(index, false)}
                disabled={sending !== null}
                className="rounded-md border border-line-strong px-3 py-1.5 text-xs text-ink hover:bg-surface-2 disabled:opacity-50"
              >
                {sending?.index === index && !sending.direct ? "Envoi…" : "Créer un brouillon"}
              </button>
              <button
                type="button"
                onClick={() => handleSend(index, true)}
                disabled={sending !== null}
                title="Upload direct (POST /api/torrents) -- part réellement en modération, contrairement au brouillon."
                className="rounded-md border border-line-strong px-3 py-1.5 text-xs text-ink hover:bg-surface-2 disabled:opacity-50"
              >
                {sending?.index === index && sending.direct ? "Envoi…" : "Uploader directement"}
              </button>
            </div>
          )}
          {integrityJobs[index] && (
            <div className="space-y-1">
              <div className="h-2 w-full overflow-hidden rounded bg-surface-2">
                <div
                  className="h-full bg-accent transition-all"
                  style={{ width: `${integrityJobs[index].percent}%` }}
                />
              </div>
              <div className="flex items-center justify-between text-xs text-ink-dim">
                <span>Vérification du fichier… — {Math.round(integrityJobs[index].percent)}%</span>
                <button type="button" onClick={() => handleCancelIntegrity(index)} className="text-crit underline">
                  Annuler
                </button>
              </div>
            </div>
          )}
          {integrityErrors[index] && <p className="text-xs text-crit">⚠ {integrityErrors[index]}</p>}
          {sendErrors[index] && <p className="text-xs text-crit">{sendErrors[index]}</p>}
          {sendResults[index] && (
            <div className="space-y-1 text-xs">
              <p className="text-good">
                {sentDirect[index] ? "Uploadé directement" : "Brouillon créé"} :{" "}
                <a
                  href={sendResults[index].draft_url}
                  className="underline"
                  target="_blank"
                  rel="noreferrer"
                >
                  {sendResults[index].draft_url}
                </a>
                <br />
                {sentDirect[index]
                  ? "Déjà envoyé en modération sur C411 — rien de plus à faire ici."
                  : "Finalise-le sur le site pour l'envoyer réellement en modération."}
              </p>
              {sendResults[index].duplicate_warning && (
                <p className="text-warn">⚠ {sendResults[index].duplicate_warning}</p>
              )}
              {sendResults[index].presentation_warning && (
                <p className="text-warn">⚠ {sendResults[index].presentation_warning}</p>
              )}
              {sendResults[index].seed_warning && (
                <p className="text-warn">⚠ {sendResults[index].seed_warning}</p>
              )}
            </div>
          )}
        </div>
      ))}
      </div>
    </div>
  );
}
