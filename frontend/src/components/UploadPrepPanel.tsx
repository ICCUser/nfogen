import { useEffect, useState } from "react";
import { prepareUploadCommit, prepareUploadPreview, sendToTracker } from "../api/client";
import { ApiError } from "../api/types";
import type { SendToTrackerResult, UploadCommitResult, UploadGroupProposal } from "../api/types";
import { useProfile } from "../ProfileContext";

/** Apercu (sans ecriture disque) puis confirmation par groupe de la mise
 * en scene + generation de .torrent (AUTOMATION.md, sous-projet 4). Un
 * groupe = un tag d'equipe detecte -- un pack assemble depuis plusieurs
 * releases devient plusieurs groupes independants (voir
 * nfogen/upload_prep.py:group_by_team). Jamais de "tout confirmer" :
 * chaque groupe se confirme individuellement, coherent avec la decision
 * "upload un par un" (AUTOMATION.md, "Decisions deja prises"). */
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
  onClose: () => void;
}) {
  const { profile: globalProfile, profiles } = useProfile();
  // Le profil actif global s'applique par defaut, mais peut etre remplace
  // juste pour CET upload sans changer le profil actif de l'appli (retour
  // utilisateur, 2026-08-29 : "selection de profil unitaire par media" --
  // ex. scanne avec le profil A, mais upload ce titre-la vers le profil B).
  const [profile, setProfile] = useState(globalProfile);
  const [groups, setGroups] = useState<UploadGroupProposal[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [recalculating, setRecalculating] = useState(false);
  // Titre corrige (AUTOMATION.md, sous-projet 5, Livraison 1) : pre-rempli
  // avec le titre DEJA CONNU (GapResult.title, Sonarr/Radarr -- le meme
  // que celui affiche dans l'en-tete du panneau juste au-dessus) plutot
  // que de redecouvrir un titre depuis le nom de fichier alors qu'on en a
  // deja un sous la main -- retour utilisateur, 2026-08-28 ("Les Fils du
  // vent" : le titre FR etait deja connu, mais jamais reutilise pour le
  // nommage). Reste editable si meme celui-la est incorrect.
  const [titleOverride, setTitleOverride] = useState(title);
  const [committing, setCommitting] = useState<number | null>(null);
  const [commitResults, setCommitResults] = useState<Record<number, UploadCommitResult>>({});
  const [commitErrors, setCommitErrors] = useState<Record<number, string>>({});
  const [sending, setSending] = useState<number | null>(null);
  const [sendResults, setSendResults] = useState<Record<number, SendToTrackerResult>>({});
  const [sendErrors, setSendErrors] = useState<Record<number, string>>({});

  async function loadPreview(override?: string, profileOverride: string = profile) {
    setRecalculating(true);
    setLoadError(null);
    try {
      const g = await prepareUploadPreview(localPaths, profileOverride, override || undefined);
      setGroups(g);
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : "Aperçu indisponible.");
    } finally {
      setRecalculating(false);
    }
  }

  useEffect(() => {
    loadPreview(title);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [localPaths]);

  function handleProfileChange(next: string) {
    setProfile(next);
    loadPreview(titleOverride, next);
  }

  async function handleConfirm(index: number, group: UploadGroupProposal) {
    if (!group.release_name) return;
    setCommitting(index);
    setCommitErrors((prev) => ({ ...prev, [index]: "" }));
    try {
      const result = await prepareUploadCommit(group.release_name, group.files, profile);
      setCommitResults((prev) => ({ ...prev, [index]: result }));
    } catch (e) {
      setCommitErrors((prev) => ({
        ...prev,
        [index]: e instanceof ApiError ? e.message : "Confirmation impossible.",
      }));
    } finally {
      setCommitting(null);
    }
  }

  async function handleSend(index: number) {
    const commit = commitResults[index];
    if (!commit) return;
    setSending(index);
    setSendErrors((prev) => ({ ...prev, [index]: "" }));
    try {
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
        draftId: sendResults[index]?.draft_id,
      });
      setSendResults((prev) => ({ ...prev, [index]: result }));
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
    <div className="space-y-3 rounded-md border border-line bg-surface p-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-sm font-semibold text-ink">Préparer l'upload — {title}</h2>
        <button type="button" onClick={onClose} className="text-sm text-ink-faint hover:text-ink">
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
      {!groups && !loadError && <p className="text-sm text-ink-faint">Calcul de l'aperçu…</p>}

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

          {!group.blocked && group.release_name && !commitResults[index] && (
            <button
              type="button"
              onClick={() => handleConfirm(index, group)}
              disabled={committing === index}
              className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-surface hover:opacity-90 disabled:opacity-50"
            >
              {committing === index ? "Confirmation…" : "Confirmer"}
            </button>
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
            <button
              type="button"
              onClick={() => handleSend(index)}
              disabled={sending === index}
              className="rounded-md border border-line-strong px-3 py-1.5 text-xs text-ink hover:bg-surface-2 disabled:opacity-50"
            >
              {sending === index ? "Envoi…" : "Envoyer à C411"}
            </button>
          )}
          {sendErrors[index] && <p className="text-xs text-crit">{sendErrors[index]}</p>}
          {sendResults[index] && (
            <div className="space-y-1 text-xs">
              <p className="text-good">
                Brouillon créé :{" "}
                <a
                  href={sendResults[index].draft_url}
                  className="underline"
                  target="_blank"
                  rel="noreferrer"
                >
                  {sendResults[index].draft_url}
                </a>
                <br />
                Finalise-le sur le site pour l'envoyer réellement en modération.
              </p>
              {sendResults[index].duplicate_warning && (
                <p className="text-warn">⚠ {sendResults[index].duplicate_warning}</p>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
