// Types miroir de nfogen/rules.schema.json et des reponses de nfogen/api.py.
// Toute evolution du schema cote Python doit se refleter ici.

export type TokenLevel = "required" | "recommended";

export interface Token {
  name: string;
  pattern: string;
  level?: TokenLevel;
  group?: string;
  error?: string;
  warning?: string;
}

export type Comparator = "int_equals" | "codec_alias";

export interface CrossCheck {
  capture: string;
  metadata_field: string;
  comparator: Comparator;
  message: string;
  aliases?: Record<string, string[]>;
}

export interface TrackLanguageCheck {
  metadata_field: string;
  label: string;
  hint_capture?: string;
  warn_if_empty?: string;
}

export interface NameProposalConfig {
  template?: string;
  language_aliases?: Record<string, string>;
}

export interface CategoryRules {
  requires_field?: string;
  doc?: string;
  example?: string;
  forbid_spaces?: boolean;
  forbid_non_ascii?: boolean;
  tokens?: Token[];
  require_one_of_groups?: Record<string, string>;
  filename_template?: string;
  cross_checks?: CrossCheck[];
  track_language_checks?: TrackLanguageCheck[];
  name_proposal?: NameProposalConfig;
}

export interface NameProposal {
  name: string | null;
  fields: Record<string, string>;
  warnings: string[];
}

export const CATEGORIES = ["video", "audio", "game", "ebook", "print3d"] as const;
export type Category = (typeof CATEGORIES)[number];

/** Reglages propres au TRACKER (pas a une categorie de media) -- voir
 * AUTOMATION.md, sous-projet 4b / nfogen/rules.schema.json $defs.tracker. */
export interface TrackerRules {
  display_name?: string;
  torznab_categories?: Record<string, string[]>;
  audio_language_codes?: Record<string, string>;
  min_request_interval_seconds?: number;
  torrent_piece_sizes?: { max_bytes?: number; piece_size: number }[];
}

export type RulesDocument = Partial<Record<Category, CategoryRules>> & { tracker?: TrackerRules };

export type TemplatesDocument = Partial<Record<Category, string>>;

export interface ManagedProfile {
  name: string;
  rules: RulesDocument;
  templates: TemplatesDocument;
}

export interface ProfilesByCategory {
  [profile: string]: string[];
}

export interface GenerateResult {
  nfo: string;
  warnings: string[];
  filename: string | null;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// --------------------------------------------------------------------------- //
// GapScan (nfogen/gapscan.py, voir GAPSCAN.md) : comparateur bibliotheque
// locale (Sonarr/Radarr) <-> catalogue C411. Types miroir des dataclasses
// Python (dataclasses.asdict cote serveur, memes noms de champs).
// --------------------------------------------------------------------------- //
export type GapStatus = "absent" | "quality_gap" | "language_gap" | "covered" | "error";

export interface ReleaseQuality {
  raw: string;
  resolution: number | null;
  source: string | null;
  codec: string | null;
  languages: string[];
  multi: boolean;
  pure: boolean;
}

export interface C411Match {
  title: string;
  guid: string;
  link: string;
  size: number | null;
  seeders: number | null;
  peers: number | null;
  grabs: number | null;
  category: string | null;
  infohash: string | null;
  imdb_id: string | null;
  tmdb_id: string | null;
  download_volume_factor: number;
  upload_volume_factor: number;
  pub_date: string | null;
  quality: ReleaseQuality;
}

export interface GapResult {
  media_type: "movie" | "series";
  title: string;
  year: number | null;
  season_number: number | null;
  imdb_id: string | null;
  tmdb_id: string | null;
  tvdb_id: number | null;
  status: GapStatus;
  local_quality: ReleaseQuality;
  c411_matches: C411Match[];
  has_freeleech_alternative: boolean;
  has_double_upload_window: boolean;
  /** Detail si status === "error" (C411 injoignable pour ce titre), sinon null. */
  error: string | null;
  /** Chemin(s) local(aux) reels apres resolution du mapping distant/local
   * (voir AUTOMATION.md, sous-projet 1). Vide/false si non resolu. */
  local_paths: string[];
  path_resolved: boolean;
  path_error: string | null;
  /** "anime"/"documentaire" d'apres la categorie C411 du premier match
   * trouve ; null si standard OU si aucun match (voir GAPSCAN.md). */
  genre: "anime" | "documentaire" | null;
  /** Identifiant Radarr/Sonarr interne (l'un ou l'autre selon media_type)
   * -- permet de recuperer des metadonnees de presentation a la demande
   * au moment d'un envoi vers un tracker (AUTOMATION.md, sous-projet 5). */
  radarr_movie_id: number | null;
  sonarr_series_id: number | null;
}

/** GET /gapscan/results : pagination cote serveur (voir GAPSCAN.md,
 * "Filtre type/genre + pagination serveur"). */
export interface GapscanResultsPage {
  items: GapResult[];
  total: number;
}

export type GapscanState = "idle" | "running" | "done" | "error";

export interface GapscanStatus {
  state: GapscanState;
  total: number;
  processed: number;
  started_at: number | null;
  finished_at: number | null;
  error: string | null;
}

export interface GapscanConfig {
  profile: string;
  tracker_configured: boolean;
  tracker_base_url: string | null;
  sonarr_configured: boolean;
  sonarr_url: string | null;
  radarr_configured: boolean;
  radarr_url: string | null;
  sonarr_path_mappings: Record<string, string>;
  radarr_path_mappings: Record<string, string>;
  /** true si une adresse d'annonce est enregistree pour ce profil --
   * jamais la valeur elle-meme (contient le passkey du compte). */
  tracker_announce_url_configured: boolean;
  staging_dir: string | null;
}

/** PUT /gapscan/config : chaque champ omis reste inchange cote serveur.
 * `tracker_*` sont namespaces par `profile` (voir AUTOMATION.md,
 * sous-projet 4b). */
export interface GapscanConfigWrite {
  profile?: string;
  tracker_api_key?: string;
  tracker_base_url?: string;
  tracker_announce_url?: string;
  sonarr_url?: string;
  sonarr_api_key?: string;
  radarr_url?: string;
  radarr_api_key?: string;
  sonarr_path_mappings?: Record<string, string>;
  radarr_path_mappings?: Record<string, string>;
  staging_dir?: string;
}

// --------------------------------------------------------------------------- //
// Preparation d'upload (AUTOMATION.md, sous-projet 4) : nommage -> mise en
// scene + .torrent, a partir des chemins locaux deja resolus par GapScan.
// --------------------------------------------------------------------------- //
export interface UploadPrepFile {
  source_path: string;
  staged_name: string;
}

export interface UploadGroupProposal {
  /** null si aucune proposition n'a pu etre calculee pour ce groupe. */
  release_name: string | null;
  files: UploadPrepFile[];
  warnings: string[];
  /** true : ce groupe ne peut pas etre confirme (voir warnings pour le detail). */
  blocked: boolean;
}

export interface UploadCommitResult {
  release_name: string;
  staged_path: string;
  torrent_path: string;
  nfo_path: string;
}

/** POST /gapscan/prepare-upload/send : cree/met a jour un BROUILLON C411
 * -- n'entre jamais en file de moderation tout seul (voir AUTOMATION.md,
 * sous-projet 5, decision 6). */
export interface SendToTrackerResult {
  draft_id: number | string;
  draft_url: string;
  duplicate_warning: string | null;
}
