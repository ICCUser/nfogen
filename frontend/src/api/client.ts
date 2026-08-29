import { getBaseUrl } from "./settings";
import type {
  GapscanConfig,
  GapscanConfigWrite,
  GapscanResultsPage,
  GapscanStatus,
  GenerateResult,
  ManagedProfile,
  NameProposal,
  ProfilesByCategory,
  RulesDocument,
  TemplatesDocument,
  UploadCommitResult,
  UploadGroupProposal,
  UploadPrepFile,
} from "./types";
import { ApiError } from "./types";

/** Enveloppe fetch() pour transformer un echec reseau (connexion perdue en
 * cours d'envoi, serveur injoignable...) en ApiError, comme une reponse HTTP
 * classique. Sans ca, ces echecs remontent comme une exception generique et
 * l'UI affiche un message inexploitable ("Erreur inattendue"). */
async function safeFetch(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch {
    throw new ApiError(
      0,
      "Connexion perdue avec le serveur (reseau interrompu, fichier trop volumineux, ou serveur indisponible).",
    );
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  // credentials: "include" -- l'authentification se fait via le cookie de
  // session httpOnly pose par POST /login (nfogen/api.py), jamais via un
  // en-tete construit ici : ce module n'a plus jamais acces au token.
  const resp = await safeFetch(`${getBaseUrl()}${path}`, { ...init, headers, credentials: "include" });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail ?? detail;
    } catch {
      // pas de corps JSON (ex. erreur reseau côté proxy) : on garde statusText
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  const contentType = resp.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return (await resp.json()) as T;
  }
  return (await resp.text()) as unknown as T;
}

// --------------------------------------------------------------------------- //
// Registre complet (tous profils, y compris C411 livre/lecture seule)
// --------------------------------------------------------------------------- //
export function listAllProfiles(): Promise<ProfilesByCategory> {
  return request<ProfilesByCategory>("/profiles");
}

// --------------------------------------------------------------------------- //
// Profils utilisateur geres dynamiquement (NFOGEN_PROFILES_DIR)
// --------------------------------------------------------------------------- //
export function listManagedProfiles(): Promise<string[]> {
  return request<string[]>("/profiles/store");
}

export function readManagedProfile(name: string): Promise<ManagedProfile> {
  return request<ManagedProfile>(`/profiles/store/${encodeURIComponent(name)}`);
}

export function writeManagedProfile(
  name: string,
  rules: RulesDocument,
  templates: TemplatesDocument,
): Promise<void> {
  return request(`/profiles/store/${encodeURIComponent(name)}`, {
    method: "PUT",
    body: JSON.stringify({ rules, templates }),
  });
}

export function deleteManagedProfile(name: string): Promise<void> {
  return request(`/profiles/store/${encodeURIComponent(name)}`, { method: "DELETE" });
}

export async function exportManagedProfile(name: string): Promise<Blob> {
  const resp = await safeFetch(`${getBaseUrl()}/profiles/store/${encodeURIComponent(name)}/export`, {
    credentials: "include",
  });
  if (!resp.ok) throw new ApiError(resp.status, resp.statusText);
  return resp.blob();
}

export function importManagedProfile(name: string, file: File): Promise<void> {
  const form = new FormData();
  form.append("file", file);
  return request(`/profiles/store/${encodeURIComponent(name)}/import`, {
    method: "POST",
    body: form,
  });
}

// --------------------------------------------------------------------------- //
// Comptes administrateurs nommes (NFOGEN_ACCOUNTS_FILE), alternative au
// token partage -- meme role unique, juste un acces individuel revocable.
// --------------------------------------------------------------------------- //
export function listAccounts(): Promise<string[]> {
  return request<string[]>("/accounts");
}

export function createAccount(username: string, password: string): Promise<void> {
  return request("/accounts", { method: "POST", body: JSON.stringify({ username, password }) });
}

export function deleteAccount(username: string): Promise<void> {
  return request(`/accounts/${encodeURIComponent(username)}`, { method: "DELETE" });
}

// --------------------------------------------------------------------------- //
// Proposition de nom (noms de fichiers seuls, aucun upload)
// --------------------------------------------------------------------------- //
export function proposeReleaseName(opts: {
  profile: string;
  category: string;
  filenames: string[];
  titleHints?: (string | null)[];
}): Promise<NameProposal> {
  const { titleHints, ...rest } = opts;
  return request<NameProposal>("/propose-name", {
    method: "POST",
    body: JSON.stringify({ ...rest, title_hints: titleHints }),
  });
}

// --------------------------------------------------------------------------- //
// Generation (apercu live)
// --------------------------------------------------------------------------- //
export async function previewGenerate(
  profile: string,
  category: string,
  data: Record<string, unknown>,
): Promise<GenerateResult> {
  const resp = await safeFetch(`${getBaseUrl()}/generate/json`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ profile, category, data }),
  });
  const warnings = (resp.headers.get("X-Nfogen-Warnings") || "")
    .split(" | ")
    .filter(Boolean);
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch {
      // ignore
    }
    throw new ApiError(resp.status, detail);
  }
  const nfo = await resp.text();
  return { nfo, warnings, filename: null };
}

/** Genere un NFO a partir de metadonnees deja extraites (POST
 * /generate/json), sans upload de fichier -- typiquement `data.raw_text` +
 * `data.video_metadata` extraits cote navigateur via WebAssembly (voir
 * `src/lib/clientMediaInfo.ts`). Demande `?download=1` pour recuperer aussi
 * le nom de fichier impose par le profil, comme `generateUpload`. */
export async function generateFromMetadata(opts: {
  profile: string;
  category: string;
  data: Record<string, unknown>;
}): Promise<GenerateResult> {
  const resp = await safeFetch(`${getBaseUrl()}/generate/json?download=1`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(opts),
  });
  const warnings = (resp.headers.get("X-Nfogen-Warnings") || "").split(" | ").filter(Boolean);
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch {
      // ignore
    }
    throw new ApiError(resp.status, detail);
  }
  const disposition = resp.headers.get("content-disposition") || "";
  const match = /filename="(.+?)"/.exec(disposition);
  const nfo = await resp.text();
  return { nfo, warnings, filename: match?.[1] ?? null };
}

function buildUploadForm(opts: {
  profile: string;
  category?: string;
  data: Record<string, unknown>;
  files: File[];
}): FormData {
  const form = new FormData();
  form.append("profile", opts.profile);
  if (opts.category) form.append("category", opts.category);
  form.append("data", JSON.stringify(opts.data ?? {}));
  for (const file of opts.files) form.append("files", file);
  return form;
}

/** Genere un NFO a partir de fichier(s) uploade(s) (POST /generate,
 * multipart) — l'equivalent de `curl -F files=@...` ou de la CLI, mais
 * depuis le navigateur. Demande toujours `?download=1` pour recuperer au
 * passage le nom de fichier impose par le profil (Content-Disposition) :
 * UN SEUL upload sert a la fois l'affichage et le telechargement (voir
 * `GeneratePage.tsx` -- reuploader pour le seul bouton "Telecharger" double
 * inutilement le temps d'attente sur des fichiers volumineux). */
export async function generateUpload(opts: {
  profile: string;
  category?: string;
  data: Record<string, unknown>;
  files: File[];
}): Promise<GenerateResult> {
  const resp = await safeFetch(`${getBaseUrl()}/generate?download=1`, {
    method: "POST",
    credentials: "include",
    body: buildUploadForm(opts),
  });
  const warnings = (resp.headers.get("X-Nfogen-Warnings") || "").split(" | ").filter(Boolean);
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch {
      // ignore
    }
    throw new ApiError(resp.status, detail);
  }
  const disposition = resp.headers.get("content-disposition") || "";
  const match = /filename="(.+?)"/.exec(disposition);
  const nfo = await resp.text();
  return { nfo, warnings, filename: match?.[1] ?? null };
}

/** Declenche un telechargement cote navigateur a partir d'un NFO deja
 * recupere (voir `generateUpload`) : pas de nouvel appel reseau, donc pas de
 * nouvel upload des fichiers source. */
export function downloadAsFile(nfo: string, filename: string): void {
  const blob = new Blob([nfo], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Meme mecanisme que `downloadAsFile`, mais a partir d'un Blob deja
 * recupere (export CSV, voir `gapscanExportCsv`) plutot que d'une chaine. */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// --------------------------------------------------------------------------- //
// GapScan (voir GAPSCAN.md) : comparateur bibliotheque locale <-> C411.
// Configuration exclusivement par variables d'environnement cote serveur
// (jamais via l'API, comme NFOGEN_API_TOKEN) : pas de fonction d'ecriture
// ici, seulement lecture de l'etat de configuration.
// --------------------------------------------------------------------------- //
export function gapscanConfig(): Promise<GapscanConfig> {
  return request<GapscanConfig>("/gapscan/config");
}

/** Enregistre cote serveur (fichier NFOGEN_GAPSCAN_CONFIG_FILE) : seuls les
 * champs fournis changent, les autres restent inchanges. Les cles ne sont
 * jamais renvoyees, meme dans la reponse de cet appel. */
export function gapscanConfigWrite(fields: GapscanConfigWrite): Promise<GapscanConfig> {
  return request<GapscanConfig>("/gapscan/config", { method: "PUT", body: JSON.stringify(fields) });
}

/** `incremental` : reprend les titres deja couverts et inchanges du
 * dernier scan sans les reinterroger sur C411 (voir GAPSCAN.md, section
 * "Persistance des resultats + scan incremental"). `only` : ne scanne que
 * les films ou que les series, pour repartir la charge sur plusieurs
 * sessions (limite C411 confirmee : 15 requetes/min). */
export function gapscanRun(incremental = false, only?: "movies" | "series"): Promise<{ status: string }> {
  const params = new URLSearchParams();
  if (incremental) params.set("incremental", "true");
  if (only) params.set("only", only);
  const qs = params.toString();
  return request(`/gapscan/run${qs ? `?${qs}` : ""}`, { method: "POST" });
}

export function gapscanStatus(): Promise<GapscanStatus> {
  return request<GapscanStatus>("/gapscan/status");
}

export function gapscanResults(
  opts: {
    status?: string;
    mediaType?: "movie" | "series";
    genre?: "anime" | "documentaire";
    page?: number;
    pageSize?: number;
  } = {},
): Promise<GapscanResultsPage> {
  const params = new URLSearchParams();
  if (opts.status) params.set("status", opts.status);
  if (opts.mediaType) params.set("media_type", opts.mediaType);
  if (opts.genre) params.set("genre", opts.genre);
  params.set("page", String(opts.page ?? 1));
  params.set("page_size", String(opts.pageSize ?? 50));
  return request<GapscanResultsPage>(`/gapscan/results?${params.toString()}`);
}

export async function gapscanExportCsv(
  opts: {
    status?: string;
    mediaType?: "movie" | "series";
    genre?: "anime" | "documentaire";
  } = {},
): Promise<Blob> {
  const params = new URLSearchParams();
  if (opts.status) params.set("status", opts.status);
  if (opts.mediaType) params.set("media_type", opts.mediaType);
  if (opts.genre) params.set("genre", opts.genre);
  const qs = params.toString();
  const resp = await safeFetch(`${getBaseUrl()}/gapscan/results/export.csv${qs ? `?${qs}` : ""}`, {
    credentials: "include",
  });
  if (!resp.ok) throw new ApiError(resp.status, resp.statusText);
  return resp.blob();
}

// --------------------------------------------------------------------------- //
// Preparation d'upload (AUTOMATION.md, sous-projet 4)
// --------------------------------------------------------------------------- //
/** Aucune ecriture disque cote serveur -- calcule uniquement les noms
 * proposes et les avertissements (voir nfogen/upload_prep.py:preview_upload). */
export function prepareUploadPreview(
  localPaths: string[],
  profile = "c411",
  titleOverride?: string,
): Promise<UploadGroupProposal[]> {
  return request<UploadGroupProposal[]>("/gapscan/prepare-upload/preview", {
    method: "POST",
    body: JSON.stringify({ local_paths: localPaths, profile, title_override: titleOverride }),
  });
}

/** Met en scene (hardlink/copie) et genere le .torrent pour UN groupe deja
 * renvoye par `prepareUploadPreview` -- renvoyer exactement ce que
 * l'apercu a produit pour ce groupe (voir nfogen/upload_prep.py:commit_upload). */
export function prepareUploadCommit(
  releaseName: string,
  files: UploadPrepFile[],
  profile = "c411",
): Promise<UploadCommitResult> {
  return request<UploadCommitResult>("/gapscan/prepare-upload/commit", {
    method: "POST",
    body: JSON.stringify({ release_name: releaseName, files, profile }),
  });
}
