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
