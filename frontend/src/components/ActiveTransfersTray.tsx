import { useEffect, useRef, useState } from "react";
import { cancelCommitJob, listCommitJobs } from "../api/client";
import type { CommitJob } from "../api/types";

const STEP_LABELS: Record<string, string> = {
  staging: "Mise en scène",
  generating_nfo: "Génération du .nfo",
  building_torrent: "Génération du torrent",
};

const ACTIVE_STATES = ["staging", "generating_nfo", "building_torrent"];

/** Encart INDEPENDANT de tout panneau "Preparer l'upload" ouvert -- visible
 * meme apres un rechargement de page (AUTOMATION.md, sous-projet 4c) :
 * interroge GET /gapscan/commit-jobs au montage, puis en continu tant qu'au
 * moins une tache est active. N'affiche que les taches NON terminales --
 * une fois done/error/cancelled, le resultat reste visible dans le panneau
 * d'origine (s'il est encore ouvert) ; pas de mecanisme de "rejet" ici, le
 * registre serveur n'est jamais purge (voir commit_job_runner.py). Masque
 * si aucune tache active. */
export default function ActiveTransfersTray() {
  const [jobs, setJobs] = useState<CommitJob[]>([]);
  const pollRef = useRef<number | null>(null);

  async function refresh() {
    try {
      const all = await listCommitJobs();
      setJobs(all);
    } catch {
      // best effort -- pas d'erreur bloquante pour un simple encart de suivi
    }
  }

  async function handleCancel(jobId: string) {
    try {
      await cancelCommitJob(jobId);
    } catch {
      // best effort -- si la tache s'est deja terminee entre-temps (404),
      // le prochain refresh() reflete l'etat reel de toute facon
    } finally {
      refresh();
    }
  }

  useEffect(() => {
    refresh();
    return () => {
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const visible = jobs.filter((j) => ACTIVE_STATES.includes(j.state));

  useEffect(() => {
    const hasActive = visible.length > 0;
    if (hasActive && pollRef.current === null) {
      pollRef.current = window.setInterval(refresh, 1500);
    } else if (!hasActive && pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible.length]);

  if (visible.length === 0) return null;

  return (
    <div className="space-y-2 rounded-md border border-line bg-surface p-3">
      <h2 className="font-display text-xs font-semibold text-ink-dim">Transferts en cours</h2>
      {visible.map((job) => (
        <div key={job.job_id} className="space-y-1">
          <div className="flex items-center justify-between text-xs text-ink">
            <span className="font-mono">{job.release_name}</span>
            <button type="button" onClick={() => handleCancel(job.job_id)} className="text-crit underline">
              Annuler
            </button>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded bg-surface-2">
            <div className="h-full bg-accent transition-all" style={{ width: `${job.percent}%` }} />
          </div>
          <p className="text-xs text-ink-dim">
            {STEP_LABELS[job.state] ?? job.state} — {Math.round(job.percent)}%
          </p>
        </div>
      ))}
    </div>
  );
}
