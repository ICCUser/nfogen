// Reglages de connexion a l'API, persistes en localStorage (pas de backend
// dedie a la config : ce sont des reglages purement cote navigateur).

const BASE_URL_KEY = "nfogen.apiBaseUrl";
const TOKEN_KEY = "nfogen.apiToken";

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

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(value: string): void {
  localStorage.setItem(TOKEN_KEY, value);
}
