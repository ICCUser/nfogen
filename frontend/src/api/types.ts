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

export type RulesDocument = Partial<Record<Category, CategoryRules>>;

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
  c411_configured: boolean;
  c411_base_url: string | null;
  sonarr_configured: boolean;
  sonarr_url: string | null;
  radarr_configured: boolean;
  radarr_url: string | null;
  sonarr_path_mappings: Record<string, string>;
  radarr_path_mappings: Record<string, string>;
}

/** PUT /gapscan/config : chaque champ omis reste inchange cote serveur. */
export interface GapscanConfigWrite {
  c411_api_key?: string;
  c411_base_url?: string;
  sonarr_url?: string;
  sonarr_api_key?: string;
  radarr_url?: string;
  radarr_api_key?: string;
  sonarr_path_mappings?: Record<string, string>;
  radarr_path_mappings?: Record<string, string>;
}
