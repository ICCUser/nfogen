import { useState } from "react";
import { previewGenerate } from "../api/client";
import { ApiError } from "../api/types";
import type { Category } from "../api/types";

interface Props {
  profile: string;
  category: Category;
}

const SAMPLE_PLACEHOLDER = `{
  "title": "Exemple",
  "release_name": "Mon.Titre-TEAM"
}`;

/** Apercu live : envoie des donnees d'exemple a /generate/json (avec le
 * profil/categorie courants) et affiche le NFO rendu + les avertissements,
 * sans rien ecrire sur disque. Utilise pour valider un template/regle avant
 * de l'utiliser en conditions reelles. */
export default function PreviewPanel({ profile, category }: Props) {
  const [sampleData, setSampleData] = useState(SAMPLE_PLACEHOLDER);
  const [nfo, setNfo] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function run() {
    setLoading(true);
    setError(null);
    setNfo(null);
    try {
      const data = JSON.parse(sampleData || "{}");
      const result = await previewGenerate(profile, category, data);
      setNfo(result.nfo);
      setWarnings(result.warnings);
    } catch (e) {
      if (e instanceof SyntaxError) setError("JSON d'exemple invalide.");
      else setError(e instanceof ApiError ? e.message : "Erreur inattendue.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">
        Données d'exemple (équivalent de <code className="rounded bg-slate-100 px-1">data</code> dans
        l'API) — n'écrit rien sur disque, n'affecte aucun profil.
      </p>
      <textarea
        className="w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-xs"
        rows={6}
        value={sampleData}
        onChange={(e) => setSampleData(e.target.value)}
      />
      <button
        type="button"
        onClick={run}
        disabled={loading}
        className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
      >
        {loading ? "Génération…" : "Tester"}
      </button>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {warnings.length > 0 && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          <p className="font-medium">Avertissements :</p>
          <ul className="list-disc pl-5">
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {nfo !== null && (
        <pre className="max-h-96 overflow-auto rounded-md border border-slate-200 bg-white p-3 text-xs">
          {nfo}
        </pre>
      )}
    </div>
  );
}
