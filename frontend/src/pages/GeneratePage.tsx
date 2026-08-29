import { useEffect, useState } from "react";
import {
  downloadAsFile,
  generateFromMetadata,
  generateUpload,
  proposeReleaseName,
} from "../api/client";
import { ApiError } from "../api/types";
import type { NameProposal } from "../api/types";
import { extractGeneralTitles, extractVideoData } from "../lib/clientMediaInfo";
import { useProfile } from "../ProfileContext";

const SAMPLE_PLACEHOLDER = `{
  "release_name": "Mon.Titre-TEAM"
}`;

// Miroir cote client de la detection par extension de nfogen/engine.py
// (detect_category) : seulement pour pre-remplir le select "Categorie" a la
// selection des fichiers (transparent, modifiable) -- la detection qui fait
// foi reste celle du serveur quand la categorie est laissee sur "auto".
const VIDEO_EXTS = [".mkv", ".mp4", ".avi", ".m2ts", ".ts", ".mov", ".wmv", ".m4v"];
const AUDIO_EXTS = [".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma"];
const EBOOK_EXTS = [".epub", ".pdf", ".cbr", ".cbz", ".mobi", ".azw3", ".djvu"];
const PRINT3D_EXTS = [".stl", ".3mf", ".obj", ".gcode", ".step", ".stp"];

function detectCategoryFromFiles(selected: File[]): string | null {
  const exts = new Set(
    selected.map((f) => {
      const i = f.name.lastIndexOf(".");
      return i >= 0 ? f.name.slice(i).toLowerCase() : "";
    }),
  );
  const hasAny = (list: string[]) => list.some((ext) => exts.has(ext));
  if (hasAny(VIDEO_EXTS)) return "video";
  if (hasAny(AUDIO_EXTS)) return "audio";
  if (hasAny(EBOOK_EXTS)) return "ebook";
  if (hasAny(PRINT3D_EXTS)) return "print3d";
  return null;
}

/** Page d'accueil : generer un NFO en envoyant directement un ou plusieurs
 * fichiers (la "troisieme voie", en plus de la bibliotheque Python et de
 * l'API appelee par script). Repose sur POST /generate (multipart), le meme
 * endpoint que la CLI/les exemples curl du README. */
export default function GeneratePage() {
  const { profile, profiles } = useProfile();
  const [category, setCategory] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [dataText, setDataText] = useState(SAMPLE_PLACEHOLDER);
  const [nfo, setNfo] = useState<string | null>(null);
  const [nfoFilename, setNfoFilename] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [proposal, setProposal] = useState<NameProposal | null>(null);
  const [proposalUnavailable, setProposalUnavailable] = useState<string | null>(null);
  const [loadingLabel, setLoadingLabel] = useState("Génération…");
  const [extractionNotice, setExtractionNotice] = useState<string | null>(null);

  // Le profil actif change ailleurs (selecteur global, entete de App.tsx) :
  // une categorie deja choisie pour l'ANCIEN profil peut ne plus exister
  // pour le nouveau -- reprend le comportement de l'ancien selecteur local
  // ("auto-detectee" par defaut a chaque changement de profil).
  useEffect(() => {
    setCategory("");
  }, [profile]);

  const categories = profiles[profile] ?? [];

  // Proposition automatique de release_name a partir des NOMS de fichiers
  // (jamais leur contenu : pas d'upload necessaire, instantane meme pour des
  // fichiers volumineux). Pour la video, on tente en plus de lire le tag
  // `Title` du conteneur (piste General) de chaque fichier -- souvent
  // renseigne a la main par l'auteur de la release avec un descriptif complet
  // (resolution, codec, equipe...), donc plus fiable qu'un nom de fichier
  // parfois generique. C'est une lecture d'en-tete locale (WebAssembly, pas
  // d'upload), best-effort : si elle echoue, la proposition se base sur les
  // seuls noms de fichiers, comme avant. Un 400 ("pas de name_proposal
  // configure pour ce profil/categorie") est silencieux : ce n'est pas une
  // erreur, juste une fonctionnalite absente pour ce profil. Toute AUTRE
  // erreur (token invalide, serveur indisponible...) est affichee : sinon
  // l'echec est invisible et ressemble a "rien ne se passe".
  useEffect(() => {
    if (!category || files.length === 0) {
      setProposal(null);
      setProposalUnavailable(null);
      return;
    }
    let cancelled = false;
    (async () => {
      let titleHints: (string | null)[] | undefined;
      if (category === "video") {
        try {
          titleHints = await extractGeneralTitles(files);
        } catch {
          titleHints = undefined;
        }
      }
      if (cancelled) return;
      proposeReleaseName({ profile, category, filenames: files.map((f) => f.name), titleHints })
        .then((result) => {
          if (cancelled) return;
          setProposal(result);
          setProposalUnavailable(null);
          if (result.name) {
            setDataText((current) => {
              let parsed: Record<string, unknown> = {};
              try {
                parsed = JSON.parse(current || "{}");
              } catch {
                parsed = {};
              }
              parsed.release_name = result.name;
              return JSON.stringify(parsed, null, 2);
            });
          }
        })
        .catch((e) => {
          if (cancelled) return;
          setProposal(null);
          setProposalUnavailable(e instanceof ApiError && e.status !== 400 ? e.message : null);
        });
    })();
    return () => {
      cancelled = true;
    };
  }, [profile, category, files]);

  function parseData(): Record<string, unknown> | null {
    try {
      return JSON.parse(dataText || "{}");
    } catch {
      setError("Le champ « métadonnées » contient un JSON invalide.");
      return null;
    }
  }

  // Pour la categorie video, le texte MediaInfo est extrait LOCALEMENT
  // (WebAssembly, cf. src/lib/clientMediaInfo.ts) plutot que d'uploader les
  // fichiers : seules quelques Ko de texte+metadonnees partent au serveur
  // (POST /generate/json), au lieu de potentiellement plusieurs Go. C'est ce
  // qui ramene la generation web a ~2s au lieu de plusieurs dizaines de
  // secondes pour un pack saison. Si l'extraction locale echoue pour une
  // raison quelconque (navigateur sans WebAssembly, fichier illisible...),
  // on retombe sur l'envoi classique (upload multipart) plutot que de
  // bloquer l'utilisateur.
  async function run() {
    if (!category && files.length === 0) {
      setError("Choisissez une catégorie, ou ajoutez un fichier pour la détection automatique.");
      return;
    }
    const data = parseData();
    if (data === null) return;

    setLoading(true);
    setError(null);
    setNfo(null);
    setNfoFilename(null);
    setExtractionNotice(null);
    try {
      let result;
      if (category === "video" && files.length > 0) {
        // Seul un echec de L'EXTRACTION elle-meme (extractVideoData) bascule
        // sur l'upload classique : une erreur renvoyee par le serveur APRES
        // une extraction reussie (ex. release_name non conforme, 400) est
        // une erreur de validation normale, pas un probleme d'extraction --
        // elle doit s'afficher telle quelle, pas declencher un second essai
        // par upload qui echouerait de toute facon pour la meme raison.
        let extracted: Awaited<ReturnType<typeof extractVideoData>> | null = null;
        try {
          setLoadingLabel("Extraction locale (aucun envoi de fichier)…");
          extracted = await extractVideoData(files);
        } catch {
          setExtractionNotice(
            "Extraction locale indisponible : envoi classique des fichiers utilisé à la place (plus lent).",
          );
        }
        if (extracted) {
          setLoadingLabel("Génération…");
          result = await generateFromMetadata({
            profile,
            category,
            data: { ...data, raw_text: extracted.rawText, video_metadata: extracted.metadata },
          });
        } else {
          setLoadingLabel("Envoi des fichiers…");
          result = await generateUpload({ profile, category, data, files });
        }
      } else {
        result = await generateUpload({ profile, category: category || undefined, data, files });
      }
      setNfo(result.nfo);
      setNfoFilename(result.filename);
      setWarnings(result.warnings);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Erreur inattendue.");
    } finally {
      setLoading(false);
      setLoadingLabel("Génération…");
    }
  }

  // Pas de nouvel appel reseau : le NFO et son nom de fichier ont deja ete
  // recuperes par run() (un seul upload, cf. generateUpload). Reuploader les
  // fichiers source juste pour ce bouton doublerait inutilement l'attente.
  function download() {
    if (nfo === null) return;
    downloadAsFile(nfo, nfoFilename || `${category || profile}.nfo`);
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-display text-xl font-semibold text-ink">Générer un NFO</h1>
        <p className="text-sm text-ink-dim">
          Envoyez un fichier (ou plusieurs, pour un album) et générez le NFO directement depuis le
          navigateur — l'équivalent de la bibliothèque Python ou d'un appel d'API en script. Pour la
          vidéo, l'analyse se fait localement dans le navigateur (aucun envoi de fichier).
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 rounded-md border border-line bg-surface p-4">
        <label className="block text-sm font-medium text-ink-dim">
          Catégorie
          <select
            className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="">(auto-détectée depuis le fichier)</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>

        <label className="col-span-2 block text-sm font-medium text-ink-dim">
          Fichier(s) source — vidéo seule, ou plusieurs fichiers audio pour un album
          <input
            type="file"
            multiple
            className="mt-1 block w-full text-sm text-ink-dim"
            onChange={(e) => {
              const selected = Array.from(e.target.files ?? []);
              setFiles(selected);
              if (!category) {
                const detected = detectCategoryFromFiles(selected);
                if (detected && categories.includes(detected)) setCategory(detected);
              }
            }}
          />
          {files.length > 0 && (
            <ul className="mt-1 list-disc pl-5 font-mono text-xs text-ink-faint">
              {files.map((f) => (
                <li key={f.name}>
                  {f.name} ({(f.size / 1024 / 1024).toFixed(1)} Mo)
                </li>
              ))}
            </ul>
          )}
        </label>

        <label className="col-span-2 block text-sm font-medium text-ink-dim">
          Métadonnées complémentaires (JSON — ex. release_name, title, requirements…)
          <textarea
            className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 font-mono text-xs text-ink"
            rows={5}
            value={dataText}
            onChange={(e) => setDataText(e.target.value)}
          />
        </label>
      </div>

      {extractionNotice && (
        <div className="rounded-md border border-warn bg-warn-bg px-4 py-3 text-sm text-warn">
          {extractionNotice}
        </div>
      )}

      {proposalUnavailable && (
        <div className="rounded-md border border-crit bg-crit-bg px-4 py-3 text-sm text-crit">
          Proposition de nom indisponible : {proposalUnavailable} (vérifiez le token API dans Réglages).
        </div>
      )}

      {proposal && proposal.name === null && (
        <div className="rounded-md border border-warn bg-warn-bg px-4 py-3 text-sm text-warn">
          <p className="font-medium">Proposition de nom impossible :</p>
          <ul className="list-disc pl-5">
            {proposal.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {proposal && proposal.name !== null && proposal.warnings.length > 0 && (
        <div className="rounded-md border border-warn bg-warn-bg px-4 py-3 text-sm text-warn">
          <p className="font-medium">
            release_name proposé : <code className="font-mono">{proposal.name}</code> — à vérifier avant de générer :
          </p>
          <ul className="list-disc pl-5">
            {proposal.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={run}
          disabled={loading}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90 disabled:opacity-50"
        >
          {loading ? loadingLabel : "Générer"}
        </button>
        <button
          type="button"
          onClick={download}
          disabled={loading || nfo === null}
          className="rounded-md border border-line-strong px-4 py-2 text-sm text-ink hover:bg-surface-2 disabled:opacity-50"
        >
          Télécharger le .nfo
        </button>
      </div>

      {error && (
        <div className="rounded-md border border-crit bg-crit-bg px-4 py-3 text-sm text-crit">
          {error}
        </div>
      )}

      {warnings.length > 0 && (
        <div className="rounded-md border border-warn bg-warn-bg px-4 py-3 text-sm text-warn">
          <p className="font-medium">Avertissements :</p>
          <ul className="list-disc pl-5">
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {nfo !== null && (
        <pre className="max-h-[32rem] overflow-auto rounded-md border border-line bg-surface p-3 font-mono text-xs text-ink">
          {nfo}
        </pre>
      )}
    </div>
  );
}
