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
        <h1 className="text-xl font-semibold text-slate-900">Profils</h1>
        <Link
          to="/profiles/new"
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
        >
          Nouveau profil
        </Link>
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error} — vérifiez les <Link to="/settings" className="underline">réglages de connexion</Link>.
        </div>
      )}

      {managedNotice && !error && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {managedNotice} — vérifiez le token dans les{" "}
          <Link to="/settings" className="underline">réglages</Link>. Les profils livrés restent visibles.
        </div>
      )}

      {rows === null && !error && <p className="text-sm text-slate-500">Chargement…</p>}

      {rows !== null && (
        <table className="w-full overflow-hidden rounded-md border border-slate-200 bg-white text-sm">
          <thead className="bg-slate-100 text-left text-slate-600">
            <tr>
              <th className="px-4 py-2">Profil</th>
              <th className="px-4 py-2">Catégories</th>
              <th className="px-4 py-2">Statut</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.name} className="border-t border-slate-100">
                <td className="px-4 py-2 font-medium text-slate-900">{row.name}</td>
                <td className="px-4 py-2 text-slate-600">{row.categories.join(", ")}</td>
                <td className="px-4 py-2">
                  {row.editable ? (
                    <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-700">
                      éditable
                    </span>
                  ) : (
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                      lecture seule (livré)
                    </span>
                  )}
                </td>
                <td className="px-4 py-2 text-right">
                  <Link to={`/profiles/${encodeURIComponent(row.name)}`} className="text-sm text-slate-700 underline">
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
