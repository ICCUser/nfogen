// Reglages de connexion a l'API. L'URL de base seule est persistee en
// localStorage (pas sensible) ; le token API ne transite plus jamais par du
// stockage navigateur lisible en JavaScript -- POST /login pose un cookie de
// session httpOnly cote serveur (nfogen/api.py), que ce module n'a jamais
// besoin de lire. Avant ce changement, le token vivait en clair dans
// localStorage (alerte CodeQL "Clear text storage of sensitive
// information"), accessible a tout script s'executant sur la page.

const BASE_URL_KEY = "nfogen.apiBaseUrl";

// En dev (`vite dev`) : "/api", proxy vers http://localhost:8000 (vite.config.ts).
// En production (`vite build`, ce que sert NFOGEN_FRONTEND_DIST) : chaine
// vide (meme origine, sans prefixe) -- nfogen/api.py monte ses routes SANS
// prefixe /api (`/profiles`, `/generate`...), donc "/api/xxx" n'existe pas
// et retombe sur le SPA fallback (index.html au lieu du JSON attendu),
// silencieusement (200 OK, juste le mauvais contenu) : c'est ce qui cassait
// le deploiement natif (scripts/install.sh) des le premier chargement, sans
// configuration manuelle prealable dans Reglages. `import.meta.env.DEV` est
// injecte par Vite au build, distingue les deux cas sans variable a definir.
// Si le frontend est servi separement de l'API (reverse-proxy sur un autre
// domaine/port), configurez l'URL reelle dans Reglages (prioritaire, stocke
// en localStorage).
const DEFAULT_BASE_URL = import.meta.env.DEV ? "/api" : "";

export function getBaseUrl(): string {
  // `??` (pas `||`) : une chaine vide explicitement enregistree (meme
  // origine, sans prefixe -- exactement la valeur qu'il faut pouvoir
  // restaurer manuellement depuis Reglages si un ancien "/api" est reste
  // enregistre) ne doit pas etre reinterpretee comme "rien n'est enregistre".
  // `localStorage.getItem` renvoie `null` (jamais `""`) quand la cle est
  // absente, donc `??` distingue bien les deux cas.
  return localStorage.getItem(BASE_URL_KEY) ?? DEFAULT_BASE_URL;
}

export function setBaseUrl(value: string): void {
  localStorage.setItem(BASE_URL_KEY, value);
}

export interface AuthStatus {
  authRequired: boolean;
  authenticated: boolean;
  /** Le token API partage (NFOGEN_API_TOKEN) peut etre utilise pour se connecter. */
  tokenLoginEnabled: boolean;
  /** Des comptes nommes (NFOGEN_ACCOUNTS_FILE) peuvent etre utilises pour se connecter. */
  accountsLoginEnabled: boolean;
  /** Aucun compte n'existe encore et rien d'autre ne protege l'instance :
   * le tout premier compte peut etre cree sans etre connecte. */
  accountsBootstrapAvailable: boolean;
}

export async function getAuthStatus(): Promise<AuthStatus> {
  const resp = await fetch(`${getBaseUrl()}/auth/status`, { credentials: "include" });
  const body = (await resp.json()) as {
    auth_required: boolean;
    authenticated: boolean;
    token_login_enabled: boolean;
    accounts_login_enabled: boolean;
    accounts_bootstrap_available: boolean;
  };
  return {
    authRequired: body.auth_required,
    authenticated: body.authenticated,
    tokenLoginEnabled: body.token_login_enabled,
    accountsLoginEnabled: body.accounts_login_enabled,
    accountsBootstrapAvailable: body.accounts_bootstrap_available,
  };
}

export type LoginCredentials = { token: string } | { username: string; password: string };

/** Verifie les identifiants auprès du serveur et, si corrects, pose le
 * cookie de session httpOnly (la reponse ne contient jamais de secret). */
export async function login(credentials: LoginCredentials): Promise<void> {
  const resp = await fetch(`${getBaseUrl()}/login`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(credentials),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || "Connexion refusee.");
  }
}

export async function logout(): Promise<void> {
  await fetch(`${getBaseUrl()}/logout`, { method: "POST", credentials: "include" });
}
