import { useEffect, useState } from "react";
import { prepareUploadCommit, prepareUploadPreview } from "../api/client";
import { ApiError } from "../api/types";
import type { UploadCommitResult, UploadGroupProposal } from "../api/types";

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
  onClose,
}: {
  localPaths: string[];
  title: string;
  onClose: () => void;
}) {
  const [groups, setGroups] = useState<UploadGroupProposal[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [recalculating, setRecalculating] = useState(false);
  // Titre corrige (AUTOMATION.md, sous-projet 5, Livraison 1) : vide par
  // defaut (garde le titre deduit du nom de fichier) -- rempli seulement
  // quand l'auto-detection se trompe (ex. "A Guy And A Girl" au lieu de
  // "Un Gars, Une Fille"), puis "Recalculer" relance l'apercu avec.
  const [titleOverride, setTitleOverride] = useState("");
  const [committing, setCommitting] = useState<number | null>(null);
  const [commitResults, setCommitResults] = useState<Record<number, UploadCommitResult>>({});
  const [commitErrors, setCommitErrors] = useState<Record<number, string>>({});

  async function loadPreview(override?: string) {
    setRecalculating(true);
    setLoadError(null);
    try {
      const g = await prepareUploadPreview(localPaths, "c411", override || undefined);
      setGroups(g);
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : "Aperçu indisponible.");
    } finally {
      setRecalculating(false);
    }
  }

  useEffect(() => {
    loadPreview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [localPaths]);

  async function handleConfirm(index: number, group: UploadGroupProposal) {
    if (!group.release_name) return;
    setCommitting(index);
    setCommitErrors((prev) => ({ ...prev, [index]: "" }));
    try {
      const result = await prepareUploadCommit(group.release_name, group.files);
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

  return (
    <div className="space-y-3 rounded-md border border-line bg-surface p-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-sm font-semibold text-ink">Préparer l'upload — {title}</h2>
        <button type="button" onClick={onClose} className="text-sm text-ink-faint hover:text-ink">
          Fermer
        </button>
      </div>

      <div className="flex items-end gap-2">
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
        </div>
      ))}
    </div>
  );
}
