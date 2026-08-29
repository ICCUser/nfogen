import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GapScanPage from "./GapScanPage";

vi.mock("../api/client", () => ({
  downloadBlob: vi.fn(),
  gapscanConfig: vi.fn(),
  gapscanConfigWrite: vi.fn(),
  gapscanExportCsv: vi.fn(),
  gapscanResults: vi.fn(),
  gapscanRun: vi.fn(),
  gapscanStatus: vi.fn(),
}));

vi.mock("../components/UploadPrepPanel", () => ({
  default: ({ title, onClose }: { title: string; onClose: () => void }) => (
    <div>
      <p>Panneau upload pour {title}</p>
      <button onClick={onClose}>Fermer le panneau</button>
    </div>
  ),
}));

import {
  gapscanConfig,
  gapscanConfigWrite,
  gapscanResults,
  gapscanRun,
  gapscanStatus,
} from "../api/client";
import type { GapResult, GapscanConfig, GapscanStatus } from "../api/types";

const CONFIGURED: GapscanConfig = {
  c411_configured: true,
  c411_base_url: "https://c411.org",
  sonarr_configured: false,
  sonarr_url: null,
  radarr_configured: true,
  radarr_url: "http://radarr.local:7878",
  sonarr_path_mappings: {},
  radarr_path_mappings: {},
  c411_announce_url_configured: false,
  staging_dir: null,
};

const IDLE_STATUS: GapscanStatus = {
  state: "idle",
  total: 0,
  processed: 0,
  started_at: null,
  finished_at: null,
  error: null,
};

const MATRIX_GAP: GapResult = {
  media_type: "movie",
  title: "Matrix",
  year: 1999,
  season_number: null,
  imdb_id: "tt0133093",
  tmdb_id: "603",
  tvdb_id: null,
  status: "absent",
  genre: null,
  local_quality: { raw: "", resolution: 2160, source: "BLURAY", codec: "X265", languages: ["VFF"], multi: true, pure: false },
  c411_matches: [],
  has_freeleech_alternative: false,
  has_double_upload_window: false,
  error: null,
  local_paths: [],
  path_resolved: true,
  path_error: null,
};

function renderPage() {
  return render(
    <MemoryRouter>
      <GapScanPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(gapscanConfig).mockResolvedValue(CONFIGURED);
  vi.mocked(gapscanStatus).mockResolvedValue(IDLE_STATUS);
  vi.mocked(gapscanResults).mockResolvedValue({ items: [], total: 0 });
});

afterEach(() => vi.resetAllMocks());

describe("GapScanPage", () => {
  it("affiche les resultats deja disponibles au chargement, avec leur statut", async () => {
    vi.mocked(gapscanResults).mockResolvedValue({ items: [MATRIX_GAP], total: 1 });

    renderPage();

    expect(await screen.findByText(/Matrix \(1999\)/)).toBeInTheDocument();
    // "Absent de C411" apparait aussi dans le select de filtre : on cible
    // le tableau pour ne pas ambiguer les deux occurrences.
    const table = within(screen.getByRole("table"));
    expect(table.getByText("Absent de C411")).toBeInTheDocument();
    expect(table.getByText(/2160p.*BLURAY.*VFF/)).toBeInTheDocument();
  });

  it("signale un chemin local non resolu par un badge, avec le detail en infobulle", async () => {
    vi.mocked(gapscanResults).mockResolvedValue({
      items: [
        { ...MATRIX_GAP, path_resolved: false, path_error: "Fichier introuvable apres resolution : /mnt/nas/Matrix.mkv" },
      ],
      total: 1,
    });

    renderPage();

    const badge = await screen.findByTitle("Fichier introuvable apres resolution : /mnt/nas/Matrix.mkv");
    expect(badge).toBeInTheDocument();
  });

  it("n'affiche pas de badge de chemin quand le chemin est resolu", async () => {
    vi.mocked(gapscanResults).mockResolvedValue({ items: [{ ...MATRIX_GAP, path_resolved: true, path_error: null }], total: 1 });

    renderPage();

    await screen.findByText(/Matrix \(1999\)/);
    expect(screen.queryByText("⚠ chemin")).not.toBeInTheDocument();
  });

  it("affiche un bouton Préparer l'upload sur une ligne avec chemin résolu, ouvre le panneau", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanResults).mockResolvedValue({
      items: [{ ...MATRIX_GAP, local_paths: ["/media/matrix.mkv"], path_resolved: true }],
      total: 1,
    });

    renderPage();

    const button = await screen.findByRole("button", { name: /Préparer l'upload/i });
    await user.click(button);

    expect(await screen.findByText("Panneau upload pour Matrix")).toBeInTheDocument();
  });

  it("n'affiche pas de bouton Préparer l'upload si le chemin n'est pas résolu", async () => {
    vi.mocked(gapscanResults).mockResolvedValue({
      items: [{ ...MATRIX_GAP, local_paths: [], path_resolved: false }],
      total: 1,
    });

    renderPage();

    await screen.findByText(/Matrix \(1999\)/);
    expect(screen.queryByRole("button", { name: /Préparer l'upload/i })).not.toBeInTheDocument();
  });

  it("chemin heureux : lancer un scan (deja termine au premier appel de statut) affiche les resultats", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanRun).mockResolvedValue({ status: "started" });
    // Le premier appel a gapscanStatus (au montage) renvoie idle ; celui
    // declenche par le clic sur "Lancer un scan" renvoie deja "done".
    vi.mocked(gapscanStatus)
      .mockResolvedValueOnce(IDLE_STATUS)
      .mockResolvedValueOnce({ ...IDLE_STATUS, state: "done", total: 1, processed: 1 });
    vi.mocked(gapscanResults)
      .mockResolvedValueOnce({ items: [], total: 0 })
      .mockResolvedValueOnce({ items: [MATRIX_GAP], total: 1 });

    renderPage();
    await screen.findByRole("button", { name: "Lancer un scan" });

    await user.click(screen.getByRole("button", { name: "Lancer un scan" }));

    expect(gapscanRun).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/Matrix \(1999\)/)).toBeInTheDocument();
    // Scan deja termine : pas de barre de progression residuelle.
    expect(screen.queryByText(/titres traités/)).not.toBeInTheDocument();
  });

  it("scan en erreur : message affiche au lieu des resultats", async () => {
    vi.mocked(gapscanStatus).mockResolvedValue({
      ...IDLE_STATUS,
      state: "error",
      error: "C411 injoignable (timeout)",
    });

    renderPage();

    expect(await screen.findByText(/C411 injoignable \(timeout\)/)).toBeInTheDocument();
  });

  it("service non configure : bouton desactive avec message explicite", async () => {
    vi.mocked(gapscanConfig).mockResolvedValue({
      c411_configured: false,
      c411_base_url: null,
      sonarr_configured: false,
      sonarr_url: null,
      radarr_configured: false,
      radarr_url: null,
      sonarr_path_mappings: {},
      radarr_path_mappings: {},
      c411_announce_url_configured: false,
      staging_dir: null,
    });

    renderPage();

    expect(await screen.findByText(/Clé API C411 non configurée/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lancer un scan" })).toBeDisabled();
    // Rien n'est configure : le formulaire doit s'ouvrir automatiquement.
    expect(screen.getByLabelText("URL Sonarr")).toBeInTheDocument();
  });

  it("enregistre Sonarr/Radarr via le formulaire de configuration", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanConfigWrite).mockResolvedValue({
      ...CONFIGURED,
      sonarr_configured: true,
      sonarr_url: "http://sonarr.local:8989",
    });

    renderPage();
    await user.click(await screen.findByRole("button", { name: /Configuration/ }));

    await user.type(screen.getByLabelText("URL Sonarr"), "http://sonarr.local:8989");
    await user.type(screen.getByLabelText("Clé API Sonarr"), "sk-123");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(gapscanConfigWrite).toHaveBeenCalledWith({
      sonarr_url: "http://sonarr.local:8989",
      sonarr_api_key: "sk-123",
      // deja remplis depuis CONFIGURED (URL/base non sensibles), renvoyes tels quels
      radarr_url: "http://radarr.local:7878",
      c411_base_url: "https://c411.org",
      sonarr_path_mappings: {},
      radarr_path_mappings: {},
    });
    expect(await screen.findByText("Enregistré.")).toBeInTheDocument();
  });

  it("enregistre un mapping de chemin Radarr via le formulaire de configuration", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanConfigWrite).mockResolvedValue({
      ...CONFIGURED,
      radarr_path_mappings: { "/data/movies": "/mnt/nas/movies" },
    });

    renderPage();
    await user.click(await screen.findByRole("button", { name: /Configuration/ }));

    // KeyValueEditor part d'une liste vide : il faut d'abord ajouter une
    // ligne avant que ses champs existent. Deux editeurs (Sonarr puis
    // Radarr, dans cet ordre dans le JSX) partagent le meme libelle de
    // bouton "+ Ajouter" (KeyValueEditor ne permet pas de le personnaliser)
    // -- le second correspond a Radarr.
    const addButtons = screen.getAllByRole("button", { name: "+ Ajouter" });
    await user.click(addButtons[1]);

    await user.type(screen.getByPlaceholderText("Chemin distant (Radarr)"), "/data/movies");
    await user.type(screen.getByPlaceholderText("Chemin local (nfogen)"), "/mnt/nas/movies");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(gapscanConfigWrite).toHaveBeenCalledWith(
      expect.objectContaining({
        radarr_path_mappings: { "/data/movies": "/mnt/nas/movies" },
      }),
    );
  });

  it("enregistre l'adresse d'annonce C411 et le dossier de mise en scene", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanConfigWrite).mockResolvedValue({
      ...CONFIGURED,
      c411_announce_url_configured: true,
      staging_dir: "/data/staging",
    });

    renderPage();
    await user.click(await screen.findByRole("button", { name: /Configuration/ }));

    await user.type(screen.getByLabelText("Adresse d'annonce C411"), "https://c411.org/announce/SECRET");
    await user.type(screen.getByLabelText("Dossier de mise en scène"), "/data/staging");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(gapscanConfigWrite).toHaveBeenCalledWith(
      expect.objectContaining({
        c411_announce_url: "https://c411.org/announce/SECRET",
        staging_dir: "/data/staging",
      }),
    );
  });

  it("pas de scan precedent : pas de case 'Scan rapide', et le scan lance est complet", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanRun).mockResolvedValue({ status: "started" });

    renderPage();
    await screen.findByRole("button", { name: "Lancer un scan" });

    expect(screen.queryByText("Scan rapide")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Lancer un scan" }));
    expect(gapscanRun).toHaveBeenCalledWith(false, undefined);
  });

  it("scan precedent disponible : case 'Scan rapide' cochee par defaut, scan lance en mode incremental", async () => {
    const user = userEvent.setup();
    const DONE_STATUS: GapscanStatus = { ...IDLE_STATUS, state: "done", total: 1, processed: 1, finished_at: 1700000000 };
    vi.mocked(gapscanStatus).mockResolvedValue(DONE_STATUS);
    vi.mocked(gapscanResults).mockResolvedValue({ items: [MATRIX_GAP], total: 1 });
    vi.mocked(gapscanRun).mockResolvedValue({ status: "started" });

    renderPage();
    const checkbox = await screen.findByRole("checkbox", { name: "Scan rapide" });
    expect(checkbox).toBeChecked();

    await user.click(screen.getByRole("button", { name: "Lancer un scan" }));
    expect(gapscanRun).toHaveBeenCalledWith(true, undefined);
  });

  it("scan precedent disponible : decocher 'Scan rapide' force un scan complet", async () => {
    const user = userEvent.setup();
    const DONE_STATUS: GapscanStatus = { ...IDLE_STATUS, state: "done", total: 1, processed: 1, finished_at: 1700000000 };
    vi.mocked(gapscanStatus).mockResolvedValue(DONE_STATUS);
    vi.mocked(gapscanResults).mockResolvedValue({ items: [MATRIX_GAP], total: 1 });
    vi.mocked(gapscanRun).mockResolvedValue({ status: "started" });

    renderPage();
    const checkbox = await screen.findByRole("checkbox", { name: "Scan rapide" });
    await user.click(checkbox);
    await user.click(screen.getByRole("button", { name: "Lancer un scan" }));

    expect(gapscanRun).toHaveBeenCalledWith(false, undefined);
  });

  it("selectionner 'Films seulement' passe only='movies' a gapscanRun", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanRun).mockResolvedValue({ status: "started" });

    renderPage();
    await screen.findByRole("button", { name: "Lancer un scan" });

    await user.selectOptions(screen.getByRole("combobox", { name: "Bibliothèque à scanner" }), "movies");
    await user.click(screen.getByRole("button", { name: "Lancer un scan" }));

    expect(gapscanRun).toHaveBeenCalledWith(false, "movies");
  });

  it("affiche les selects Type et Genre, appelle gapscanResults avec les filtres choisis", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanResults).mockResolvedValue({ items: [MATRIX_GAP], total: 1 });

    renderPage();
    await screen.findByText(/Matrix \(1999\)/);

    await user.selectOptions(screen.getByLabelText("Type"), "movie");
    await waitFor(() => {
      expect(gapscanResults).toHaveBeenLastCalledWith(
        expect.objectContaining({ mediaType: "movie", page: 1 }),
      );
    });

    await user.selectOptions(screen.getByLabelText("Genre"), "anime");
    await waitFor(() => {
      expect(gapscanResults).toHaveBeenLastCalledWith(
        expect.objectContaining({ mediaType: "movie", genre: "anime", page: 1 }),
      );
    });
  });

  it("affiche la pagination et change de page au clic sur Suivant", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanResults).mockResolvedValue({ items: [MATRIX_GAP], total: 120 });

    renderPage();
    await screen.findByText(/Page 1 \/ 3/);

    await user.click(screen.getByRole("button", { name: "Suivant" }));

    await waitFor(() => {
      expect(gapscanResults).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }));
    });
  });

  it("changer de filtre revient a la page 1", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanResults).mockResolvedValue({ items: [MATRIX_GAP], total: 120 });

    renderPage();
    await screen.findByText(/Page 1 \/ 3/);
    await user.click(screen.getByRole("button", { name: "Suivant" }));
    await waitFor(() => screen.getByText(/Page 2 \/ 3/));

    await user.selectOptions(screen.getByLabelText("Type"), "series");

    await waitFor(() => {
      expect(gapscanResults).toHaveBeenLastCalledWith(expect.objectContaining({ mediaType: "series", page: 1 }));
    });
  });
});
