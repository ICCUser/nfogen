import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "./SettingsPage";
import { ProfileProvider } from "../ProfileContext";
import type { GapscanConfig } from "../api/types";

vi.mock("../api/client", () => ({
  createAccount: vi.fn(),
  deleteAccount: vi.fn(),
  listAccounts: vi.fn(),
  listAllProfiles: vi.fn(),
  readManagedProfile: vi.fn(),
  gapscanConfig: vi.fn(),
  gapscanConfigWrite: vi.fn(),
}));
vi.mock("../api/settings", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/settings")>();
  return { ...actual, getAuthStatus: vi.fn(), login: vi.fn(), logout: vi.fn() };
});

import {
  gapscanConfig,
  gapscanConfigWrite,
  listAllProfiles,
  readManagedProfile,
} from "../api/client";
import { getAuthStatus, login } from "../api/settings";

const UNAUTHENTICATED_TOKEN_ONLY = {
  authRequired: true,
  authenticated: false,
  tokenLoginEnabled: true,
  accountsLoginEnabled: false,
  accountsBootstrapAvailable: false,
};

const CONFIGURED: GapscanConfig = {
  profile: "c411",
  tracker_configured: true,
  tracker_base_url: "https://c411.org",
  sonarr_configured: true,
  sonarr_url: "http://sonarr.local:8989",
  radarr_configured: true,
  radarr_url: "http://radarr.local:7878",
  sonarr_path_mappings: {},
  radarr_path_mappings: {},
  tracker_announce_url_configured: false,
  staging_dir: null,
  qbittorrent_configured: false,
  qbittorrent_url: null,
  qbittorrent_verify_ssl: true,
  tmdb_configured: false,
};

function renderPage() {
  return render(
    <ProfileProvider>
      <SettingsPage />
    </ProfileProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  vi.mocked(listAllProfiles).mockResolvedValue({ c411: ["video"] });
  vi.mocked(readManagedProfile).mockResolvedValue({
    name: "c411", rules: { tracker: { display_name: "C411" } }, templates: {},
  });
  vi.mocked(gapscanConfig).mockResolvedValue(CONFIGURED);
  vi.mocked(getAuthStatus).mockResolvedValue(UNAUTHENTICATED_TOKEN_ONLY);
});

afterEach(() => vi.resetAllMocks());

describe("SettingsPage - connexion par token", () => {
  it("chemin heureux : token valide -> login() appele, statut 'Connecte' affiche", async () => {
    vi.mocked(getAuthStatus)
      .mockResolvedValueOnce(UNAUTHENTICATED_TOKEN_ONLY)
      .mockResolvedValueOnce({ ...UNAUTHENTICATED_TOKEN_ONLY, authenticated: true });
    vi.mocked(login).mockResolvedValue(undefined);

    renderPage();

    const tokenInput = await screen.findByLabelText("Token API");
    await userEvent.type(tokenInput, "mon-token-secret");
    await userEvent.click(screen.getByRole("button", { name: "Se connecter" }));

    expect(login).toHaveBeenCalledWith({ token: "mon-token-secret" });
    expect(await screen.findByText("Connecté.")).toBeInTheDocument();
  });

  it("token invalide : message d'erreur affiche, formulaire de connexion toujours visible", async () => {
    vi.mocked(login).mockRejectedValue(new Error("Token API invalide."));

    renderPage();

    const tokenInput = await screen.findByLabelText("Token API");
    await userEvent.type(tokenInput, "mauvais-token");
    await userEvent.click(screen.getByRole("button", { name: "Se connecter" }));

    expect(await screen.findByText("Token API invalide.")).toBeInTheDocument();
    expect(screen.queryByText("Connecté.")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Token API")).toBeInTheDocument();
  });
});

describe("SettingsPage - configuration globale (Sonarr/Radarr/qBittorrent/TMDB)", () => {
  /* Retour utilisateur, 2026-09-07 : ce panneau vivait auparavant sur
   * LibraryPage -- migre ici car independant du profil de tracker actif
   * (voir LibraryPage.test.tsx pour le panneau "Configuration du profil"
   * qui, lui, reste sur Bibliotheque). */
  it("enregistre Sonarr via le formulaire de configuration globale", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanConfigWrite).mockResolvedValue({
      ...CONFIGURED, sonarr_url: "http://sonarr.local:8989",
    });

    renderPage();
    await user.click(await screen.findByRole("button", { name: /Configuration globale/ }));

    const sonarrUrlInput = screen.getByLabelText("URL Sonarr");
    await user.clear(sonarrUrlInput);
    await user.type(sonarrUrlInput, "http://sonarr.local:8989");
    await user.type(screen.getByLabelText("Clé API Sonarr"), "sk-123");
    // Deux boutons "Enregistrer" sur la page (URL de base API + config
    // globale) -- celui de la config globale est le dernier du DOM.
    await user.click(screen.getAllByRole("button", { name: "Enregistrer" }).at(-1)!);

    expect(gapscanConfigWrite).toHaveBeenCalledWith(
      expect.objectContaining({ sonarr_url: "http://sonarr.local:8989", sonarr_api_key: "sk-123" }),
      "c411",
    );
    expect(await screen.findByText("Enregistré.")).toBeInTheDocument();
  });

  it("enregistre la configuration qBittorrent via le formulaire de configuration globale", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanConfigWrite).mockResolvedValue({
      ...CONFIGURED, qbittorrent_configured: true, qbittorrent_url: "http://qbittorrent.local:8080",
    });

    renderPage();
    await user.click(await screen.findByRole("button", { name: /Configuration globale/ }));

    await user.type(screen.getByLabelText("URL qBittorrent"), "http://qbittorrent.local:8080");
    await user.type(screen.getByLabelText("Utilisateur qBittorrent"), "admin");
    await user.type(screen.getByLabelText("Mot de passe qBittorrent"), "secret");
    // Deux boutons "Enregistrer" sur la page (URL de base API + config
    // globale) -- celui de la config globale est le dernier du DOM.
    await user.click(screen.getAllByRole("button", { name: "Enregistrer" }).at(-1)!);

    expect(gapscanConfigWrite).toHaveBeenCalledWith(
      expect.objectContaining({
        qbittorrent_url: "http://qbittorrent.local:8080",
        qbittorrent_username: "admin",
        qbittorrent_password: "secret",
        qbittorrent_verify_ssl: true,
      }),
      "c411",
    );
  });

  it("decoche la verification SSL qBittorrent -- envoie qbittorrent_verify_ssl: false", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanConfigWrite).mockResolvedValue(CONFIGURED);

    renderPage();
    await user.click(await screen.findByRole("button", { name: /Configuration globale/ }));
    await user.click(screen.getByLabelText(/Vérifier le certificat SSL de qBittorrent/));
    // Deux boutons "Enregistrer" sur la page (URL de base API + config
    // globale) -- celui de la config globale est le dernier du DOM.
    await user.click(screen.getAllByRole("button", { name: "Enregistrer" }).at(-1)!);

    expect(gapscanConfigWrite).toHaveBeenCalledWith(
      expect.objectContaining({ qbittorrent_verify_ssl: false }),
      "c411",
    );
  });

  it("enregistre la cle API TMDB via le formulaire de configuration globale", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanConfigWrite).mockResolvedValue({ ...CONFIGURED, tmdb_configured: true });

    renderPage();
    await user.click(await screen.findByRole("button", { name: /Configuration globale/ }));
    await user.type(screen.getByLabelText("Clé API TMDB"), "tmdb-secret");
    // Deux boutons "Enregistrer" sur la page (URL de base API + config
    // globale) -- celui de la config globale est le dernier du DOM.
    await user.click(screen.getAllByRole("button", { name: "Enregistrer" }).at(-1)!);

    expect(gapscanConfigWrite).toHaveBeenCalledWith(
      expect.objectContaining({ tmdb_api_key: "tmdb-secret" }),
      "c411",
    );
  });

  it("deplie automatiquement le panneau si ni Sonarr ni Radarr ne sont configures", async () => {
    vi.mocked(gapscanConfig).mockResolvedValue({
      ...CONFIGURED, sonarr_configured: false, sonarr_url: null, radarr_configured: false, radarr_url: null,
    });

    renderPage();

    expect(await screen.findByLabelText("URL Sonarr")).toBeInTheDocument();
  });
});
