// Reglages de connexion a l'API. L'URL de base seule est persistee en
// localStorage (pas sensible) ; le token API ne transite plus jamais par du
// stockage navigateur lisible en JavaScript -- POST /login pose un cookie de
// session httpOnly cote serveur (nfogen/api.py), que ce module n'a jamais
// besoin de lire. Avant ce changement, le token vivait en clair dans
// localStorage (alerte CodeQL "Clear text storage of sensitive
// information"), accessible a tout script s'executant sur la page.

const BASE_URL_KEY = "nfogen.apiBaseUrl";

// Par defaut : "/api", proxy vers http://localhost:8000 en dev (vite.config.ts).
// En production, pointez vers l'URL reelle de l'API nfogen (ou servez le
// frontend derriere un reverse-proxy qui mappe /api -> l'API).
const DEFAULT_BASE_URL = "/api";

export function getBaseUrl(): string {
  return localStorage.getItem(BASE_URL_KEY) || DEFAULT_BASE_URL;
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
