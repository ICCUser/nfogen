import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listAllProfiles, listManagedProfiles } from "../api/client";
import { ApiError } from "../api/types";

interface Row {
  name: string;
  categories: string[];
  editable: boolean;
}

export default function ProfilesListPage() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [managedNotice, setManagedNotice] = useState<string | null>(null);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    setError(null);
    setManagedNotice(null);

    let all: Record<string, string[]>;
    try {
      all = await listAllProfiles();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Impossible de contacter l'API.");
      setRows(null);
      return;
    }

    // La liste des profils geres (NFOGEN_PROFILES_DIR) est protegee par
    // token et peut etre indisponible (pas de token configure, ou variable
    // d'environnement absente cote serveur) : ca ne doit pas empecher
    // d'afficher le registre complet (profils en lecture seule inclus).
    let managedSet = new Set<string>();
    try {
      managedSet = new Set(await listManagedProfiles());
    } catch (e) {
      setManagedNotice(
        e instanceof ApiError
          ? `Profils utilisateur indisponibles : ${e.message}`
          : "Profils utilisateur indisponibles.",
      );
    }

    setRows(
      Object.entries(all)
        .map(([name, categories]) => ({ name, categories, editable: managedSet.has(name) }))
        .sort((a, b) => a.name.localeCompare(b.name)),
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-xl font-semibold text-ink">Profils</h1>
        <Link
          to="/profiles/new"
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90"
        >
          Nouveau profil
        </Link>
      </div>

      {error && (
        <div className="rounded-md border border-crit bg-crit-bg px-4 py-3 text-sm text-crit">
          {error} — vérifiez les <Link to="/settings" className="underline">réglages de connexion</Link>.
        </div>
      )}

      {managedNotice && !error && (
        <div className="rounded-md border border-warn bg-warn-bg px-4 py-3 text-sm text-warn">
          {managedNotice} — vérifiez le token dans les{" "}
          <Link to="/settings" className="underline">réglages</Link>. Les profils livrés restent visibles.
        </div>
      )}

      {rows === null && !error && <p className="text-sm text-ink-faint">Chargement…</p>}

      {rows !== null && (
        <table className="w-full overflow-hidden rounded-md border border-line bg-surface text-sm">
          <thead className="bg-surface-2 text-left text-ink-dim">
            <tr>
              <th className="px-4 py-2">Profil</th>
              <th className="px-4 py-2">Catégories</th>
              <th className="px-4 py-2">Statut</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.name} className="border-t border-line">
                <td className="px-4 py-2 font-mono font-medium text-ink">{row.name}</td>
                <td className="px-4 py-2 text-ink-dim">{row.categories.join(", ")}</td>
                <td className="px-4 py-2">
                  {row.editable ? (
                    <span className="rounded-full bg-good-bg px-2 py-0.5 text-xs text-good">
                      éditable
                    </span>
                  ) : (
                    <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs text-ink-faint">
                      lecture seule (livré)
                    </span>
                  )}
                </td>
                <td className="px-4 py-2 text-right">
                  <Link to={`/profiles/${encodeURIComponent(row.name)}`} className="text-sm text-accent-ink underline">
                    Gérer
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
