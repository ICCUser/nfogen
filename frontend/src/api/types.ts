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

/** Une ligne du journal en direct d'un scan (retour utilisateur,
 * 2026-09-06 : voir ce qu'un scan est en train de faire, pas seulement
 * un compteur) -- ne se vide pas seul a la fin du scan, voir
 * clearGapscanLog(). */
export interface GapscanLogEntry {
  title: string;
  year: number | null;
  media_type: "movie" | "series";
  season_number: number | null;
  status: GapStatus;
}

export interface GapscanStatus {
  state: GapscanState;
  total: number;
  processed: number;
  started_at: number | null;
  finished_at: number | null;
  error: string | null;
  log: GapscanLogEntry[];
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
  qbittorrent_configured: boolean;
  qbittorrent_url: string | null;
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
  qbittorrent_url?: string;
  qbittorrent_username?: string;
  qbittorrent_password?: string;
}

// --------------------------------------------------------------------------- //
// Bibliotheque locale (AUTOMATION.md, sous-projet 8) : inventaire brut
// Radarr/Sonarr, zero appel tracker. Type miroir de nfogen/gapscan_library.py:LibraryItem.
// --------------------------------------------------------------------------- //
export interface LibraryItem {
  media_type: "movie" | "series";
  title: string;
  year: number | null;
  season_number: number | null;
  imdb_id: string | null;
  tvdb_id: number | null;
  tmdb_id: string | null;
  genres: string[];
  added_at: number | null;
  local_quality: ReleaseQuality;
  radarr_movie_id: number | null;
  sonarr_series_id: number | null;
  already_processed: boolean;
  last_processed_at: number | null;
  /** Cle opaque (voir gapscan.movie_key/series_key) -- a renvoyer telle
   * quelle dans `gapscanRun(..., selection)` pour cibler cet item. */
  key: string;
  /** Statut du DERNIER scan connu (bulk ou cible) -- `null` si ce titre
   * n'a jamais ete verifie sur le tracker (fusion Bibliotheque/Scan,
   * AUTOMATION.md sous-projet 8, retour utilisateur 2026-09-06). Jamais
   * rafraichi par un simple rechargement de la bibliotheque. */
  status: GapStatus | null;
  checked_at: number | null;
  has_freeleech_alternative: boolean;
  has_double_upload_window: boolean;
  error: string | null;
  local_paths: string[];
  path_resolved: boolean;
  path_error: string | null;
  /** Categorie C411 du match trouve (voir gapscan.genre_of) -- DISTINCT de
   * `genres` (Radarr/Sonarr) : les deux classifications restent
   * volontairement independantes. */
  tracker_genre: "anime" | "documentaire" | null;
}

export interface LibraryResultsPage {
  items: LibraryItem[];
  total: number;
}

// --------------------------------------------------------------------------- //
// File d'attente de mise en seed (AUTOMATION.md, sous-projet 6) : titres
// envoyes a C411 mais pas encore ajoutes a un client de seed. Import
// manuel du .torrent re-signe -- aucune API C411 ne permet de le
// recuperer automatiquement (verifie en conditions reelles, 2026-09-06).
// --------------------------------------------------------------------------- //
export interface SeedQueueEntry {
  key: string;
  media_type: "movie" | "series";
  release_name: string;
  staged_path: string | null;
  sent_at: number | null;
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

/** POST /gapscan/prepare-upload/commit ne bloque plus : cree une tache de
 * fond suivie via job_id (AUTOMATION.md, sous-projet 4c). */
export type CommitJobState =
  | "staging"
  | "generating_nfo"
  | "building_torrent"
  | "done"
  | "error"
  | "cancelled";

export interface CommitJob {
  job_id: string;
  release_name: string;
  state: CommitJobState;
  /** 0-100, relatif a l'ETAPE EN COURS (state). */
  percent: number;
  started_at: number;
  finished_at: number | null;
  error: string | null;
  result: UploadCommitResult | null;
}

/** POST /gapscan/prepare-upload/send : cree/met a jour un BROUILLON C411
 * -- n'entre jamais en file de moderation tout seul (voir AUTOMATION.md,
 * sous-projet 5, decision 6). */
export interface SendToTrackerResult {
  draft_id: number | string;
  draft_url: string;
  duplicate_warning: string | null;
}
