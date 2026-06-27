import mediaInfoFactory, { isTrackType } from "mediainfo.js";
import type { MediaInfo, ReadChunkFunc, Track } from "mediainfo.js";
import mediaInfoWasmUrl from "mediainfo.js/MediaInfoModule.wasm?url";

/** Extraction MediaInfo entierement cote navigateur (WebAssembly), par
 * plages d'octets via Blob.slice() -- jamais le fichier entier en memoire,
 * jamais d'upload. C'est ce qui permet a la page "Generer" de produire un
 * NFO video en quelques secondes meme pour des packs saison de plusieurs Go
 * (le texte renvoye est ensuite poste a /generate/json via `raw_text`,
 * quelques Ko au lieu des fichiers sources). Miroir cote client de
 * `nfogen/extract.py::extract_video_text`/`extract_video_dir_text` : memes
 * regles de tri/concatenation pour produire un resultat identique a celui
 * de l'upload classique (CLI/API). */

function locateFile(path: string, prefix: string): string {
  return path === "MediaInfoModule.wasm" ? mediaInfoWasmUrl : `${prefix}${path}`;
}

function makeReadChunk(file: File): ReadChunkFunc {
  return async (chunkSize, offset) => new Uint8Array(await file.slice(offset, offset + chunkSize).arrayBuffer());
}

let textInstance: Promise<MediaInfo<"text">> | null = null;
let objectInstance: Promise<MediaInfo<"object">> | null = null;

function getTextInstance(): Promise<MediaInfo<"text">> {
  if (!textInstance) textInstance = mediaInfoFactory({ format: "text", locateFile });
  return textInstance;
}

function getObjectInstance(): Promise<MediaInfo<"object">> {
  if (!objectInstance) objectInstance = mediaInfoFactory({ format: "object", locateFile });
  return objectInstance;
}

const COMPLETE_NAME_RE = /^(Complete name\s*:\s*).*$/m;
const GENERAL_HEADER_RE = /^(General)\s*$/m;

/** mediainfo.js n'a aucune notion de chemin pour un Blob analyse en memoire
 * (pas d'upload = pas de fichier reel cote serveur) : on injecte nous-meme
 * le SEUL nom de fichier (jamais un chemin) dans la ligne "Complete name",
 * pour rester structurellement identique a la sortie serveur -- qui fait
 * exactement la meme chose, pour la meme raison de confidentialite
 * (cf. nfogen/extract.py). */
function withCompleteName(text: string, filename: string): string {
  if (COMPLETE_NAME_RE.test(text)) {
    return text.replace(COMPLETE_NAME_RE, `$1${filename}`);
  }
  if (GENERAL_HEADER_RE.test(text)) {
    return text.replace(GENERAL_HEADER_RE, `$1\nComplete name                            : ${filename}`);
  }
  return text;
}

export interface ClientTrackMetadata {
  name?: string;
  video_height: number | null;
  video_format: string | null;
  audio_languages: (string | null)[];
  subtitle_languages: (string | null)[];
}

function toTrackMetadata(tracks: Track[]): Omit<ClientTrackMetadata, "name"> {
  const video = tracks.find((t) => isTrackType(t, "Video"));
  const audio = tracks.filter((t) => isTrackType(t, "Audio"));
  const text = tracks.filter((t) => isTrackType(t, "Text"));
  return {
    video_height: video?.Height ?? null,
    video_format: video?.Format ?? null,
    audio_languages: audio.map((t) => t.Language ?? null),
    subtitle_languages: text.map((t) => t.Language ?? null),
  };
}

export interface ClientVideoExtraction {
  rawText: string;
  metadata: ClientTrackMetadata[];
}

/** Un seul fichier = episode/film ; plusieurs = pack saison (tri par nom,
 * blocs textuels separes par une ligne vide), exactement comme
 * `extract_video_dir_text` cote serveur. */
export async function extractVideoData(files: File[]): Promise<ClientVideoExtraction> {
  if (files.length === 0) {
    throw new Error("Aucun fichier a analyser.");
  }
  const sorted = [...files].sort((a, b) => a.name.localeCompare(b.name));
  const textMi = await getTextInstance();
  const objectMi = await getObjectInstance();

  const textBlocks: string[] = [];
  const metadata: ClientTrackMetadata[] = [];
  for (const file of sorted) {
    const text = await textMi.analyzeData(file.size, makeReadChunk(file));
    textBlocks.push(withCompleteName(text, file.name));
    textMi.reset();

    const result = await objectMi.analyzeData(file.size, makeReadChunk(file));
    const meta = toTrackMetadata(result.media?.track ?? []);
    metadata.push(sorted.length > 1 ? { ...meta, name: file.name } : meta);
    objectMi.reset();
  }

  return { rawText: textBlocks.join("\n"), metadata };
}

/** Tag `Title` du conteneur (piste General) de chaque fichier, dans le MEME
 * ORDRE que `files` (pas trie, contrairement a `extractVideoData` qui trie
 * pour la generation) : utilise pour affiner la proposition de release_name
 * (`POST /propose-name`, voir `nfogen/name_proposal.py`) des la selection des
 * fichiers, avant generation. Souvent renseigne a la main par l'auteur de la
 * release avec un descriptif complet (resolution, codec, equipe...), donc
 * plus fiable que le seul nom de fichier. Best-effort : un fichier illisible
 * ou un tag absent donne simplement `null` pour cette entree. */
export async function extractGeneralTitles(files: File[]): Promise<(string | null)[]> {
  const objectMi = await getObjectInstance();
  const titles: (string | null)[] = [];
  for (const file of files) {
    try {
      const result = await objectMi.analyzeData(file.size, makeReadChunk(file));
      const general = result.media?.track.find((t) => isTrackType(t, "General"));
      titles.push(general?.Title ?? null);
    } catch {
      titles.push(null);
    } finally {
      objectMi.reset();
    }
  }
  return titles;
}
