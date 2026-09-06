import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { gapscanRun, libraryResults } from "../api/client";
import { ApiError } from "../api/types";
import type { LibraryItem } from "../api/types";
import { useProfile } from "../ProfileContext";

/** Page "Bibliothèque" (AUTOMATION.md, sous-projet 8) : inventaire brut
 * Radarr/Sonarr, ZERO appel tracker -- rechargement quasi instantané,
 * séparée de la page "Scan C411" (qui reste le scan bulk classique).
 * Permet de sélectionner un sous-ensemble (filtre ou case à cocher) et de
 * ne vérifier QUE lui sur le tracker, plutôt que toute la bibliothèque à
 * chaque fois (retour utilisateur, 2026-09-06). */
export default function LibraryPage() {
  const { profile } = useProfile();
  const navigate = useNavigate();
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [mediaType, setMediaType] = useState<"" | "movie" | "series">("");
  const [genre, setGenre] = useState("");
  const [addedSinceDays, setAddedSinceDays] = useState("");
  const [processed, setProcessed] = useState<"" | "true" | "false">("");
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 50;
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, mediaType, genre, addedSinceDays, processed, page, profile]);

  async function load() {
    try {
      const res = await libraryResults({
        q: q || undefined,
        mediaType: mediaType || undefined,
        genre: genre || undefined,
        addedSinceDays: addedSinceDays ? Number(addedSinceDays) : undefined,
        processed: processed === "" ? undefined : processed === "true",
        page,
        pageSize: PAGE_SIZE,
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

  async function handleVerify() {
    if (selected.size === 0) return;
    setStarting(true);
    setError(null);
    try {
      await gapscanRun(false, undefined, profile, Array.from(selected));
      navigate("/gapscan");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Impossible de lancer le scan.");
    } finally {
      setStarting(false);
    }
  }

  function resetPageAnd<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v);
      setPage(1);
    };
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-xl font-semibold text-ink">Bibliothèque</h1>
          <p className="text-sm text-ink-dim">
            Inventaire Sonarr/Radarr local — aucun appel au tracker. Sélectionne les titres à vérifier
            puis lance un scan ciblé, plutôt que toute la bibliothèque.
          </p>
        </div>
        <button
          type="button"
          onClick={handleVerify}
          disabled={selected.size === 0 || starting}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90 disabled:opacity-50"
        >
          {starting ? "Démarrage…" : `Vérifier sur le tracker (${selected.size} sélectionnés)`}
        </button>
      </div>

      {error && (
        <div className="rounded-md border border-crit bg-crit-bg px-4 py-3 text-sm text-crit">{error}</div>
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
                </td>
                <td className="px-4 py-2 text-ink-dim">
                  {item.media_type === "movie" ? "Film" : `Série S${String(item.season_number).padStart(2, "0")}`}
                </td>
                <td className="px-4 py-2 text-ink-dim">{item.genres.join(", ") || "—"}</td>
                <td className="px-4 py-2 text-ink-dim">
                  {item.already_processed ? "Déjà traité" : "Jamais traité"}
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
    </div>
  );
}
