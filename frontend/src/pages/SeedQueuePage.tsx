import { useEffect, useState } from "react";
import { addToSeedQueue, seedQueue } from "../api/client";
import { ApiError } from "../api/types";
import type { SeedQueueEntry } from "../api/types";

/** Page "À mettre en seed" (AUTOMATION.md, sous-projet 6) : titres déjà
 * envoyés à C411 (voir "Envoyer à C411", sous-projet 5) en attente du
 * `.torrent` RE-SIGNÉ par le tracker une fois la modération terminée --
 * ce fichier ne peut être récupéré qu'en le téléchargeant soi-même
 * (aucune API ne le permet, vérifié en conditions réelles) : dépose-le
 * ici une fois en main, nfogen l'ajoute au client de seed pointé sur le
 * contenu déjà mis en scène (jamais un nouveau transfert). */
export default function SeedQueuePage() {
  const [entries, setEntries] = useState<SeedQueueEntry[] | null>(null);
  const [files, setFiles] = useState<Record<string, File | undefined>>({});
  const [adding, setAdding] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      const list = await seedQueue();
      setEntries(list);
    } catch (e) {
      setEntries(null);
      setLoadError(e instanceof ApiError ? e.message : "File d'attente indisponible.");
    }
  }

  async function handleAdd(entry: SeedQueueEntry) {
    const file = files[entry.key];
    if (!file) return;
    setAdding(entry.key);
    setErrors((prev) => ({ ...prev, [entry.key]: "" }));
    try {
      await addToSeedQueue(entry.key, file);
      setEntries((prev) => (prev ? prev.filter((e) => e.key !== entry.key) : prev));
    } catch (e) {
      setErrors((prev) => ({
        ...prev,
        [entry.key]: e instanceof ApiError || e instanceof Error ? e.message : "Ajout impossible.",
      }));
    } finally {
      setAdding(null);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-display text-xl font-semibold text-ink">À mettre en seed</h1>
        <p className="text-sm text-ink-dim">
          Titres déjà envoyés au tracker, en attente du <code>.torrent</code> re-signé une fois la
          modération terminée — télécharge-le depuis le site puis dépose-le ici.
        </p>
      </div>

      {loadError && (
        <div className="rounded-md border border-crit bg-crit-bg px-4 py-3 text-sm text-crit">{loadError}</div>
      )}

      {entries === null && !loadError && <p className="text-sm text-ink-faint">Chargement…</p>}
      {entries !== null && entries.length === 0 && (
        <p className="text-sm text-ink-faint">Aucun titre en attente de mise en seed.</p>
      )}

      {entries !== null && entries.length > 0 && (
        <ul className="space-y-3">
          {entries.map((entry) => (
            <li key={entry.key} className="space-y-2 rounded-md border border-line bg-surface p-4">
              <p className="font-mono text-sm font-medium text-ink">{entry.release_name}</p>
              <div className="flex items-center gap-3">
                <label className="block text-xs font-medium text-ink-dim">
                  Fichier .torrent re-signé
                  <input
                    aria-label="Fichier .torrent re-signé"
                    type="file"
                    accept=".torrent"
                    onChange={(e) => setFiles((prev) => ({ ...prev, [entry.key]: e.target.files?.[0] }))}
                    className="mt-1 block text-sm text-ink"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => handleAdd(entry)}
                  disabled={!files[entry.key] || adding === entry.key}
                  className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-surface hover:opacity-90 disabled:opacity-50"
                >
                  {adding === entry.key ? "Ajout…" : "Ajouter au client de seed"}
                </button>
              </div>
              {errors[entry.key] && <p className="text-xs text-crit">{errors[entry.key]}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
