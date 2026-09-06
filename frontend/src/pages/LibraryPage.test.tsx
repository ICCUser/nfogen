import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  downloadBlob: vi.fn(),
  gapscanConfig: vi.fn(),
  gapscanConfigWrite: vi.fn(),
  gapscanExportCsv: vi.fn(),
  gapscanRun: vi.fn(),
  gapscanStatus: vi.fn(),
  libraryResults: vi.fn(),
  listAllProfiles: vi.fn(),
  readManagedProfile: vi.fn(),
}));

vi.mock("../components/UploadPrepPanel", () => ({
  default: (props: {
    title: string; onClose: () => void; mediaType?: string; tmdbId?: number | null;
  }) => (
    <div>
      <p>Panneau upload pour {props.title}</p>
      <p>media_type={props.mediaType}</p>
      <p>tmdb_id={String(props.tmdbId)}</p>
      <button onClick={props.onClose}>Fermer le panneau</button>
    </div>
  ),
}));

vi.mock("../components/ActiveTransfersTray", () => ({
  default: () => <div>Transferts en cours (mock)</div>,
}));

import {
  gapscanConfig,
  gapscanConfigWrite,
  gapscanRun,
  gapscanStatus,
  libraryResults,
  listAllProfiles,
  readManagedProfile,
} from "../api/client";
import LibraryPage from "./LibraryPage";
import { ProfileProvider } from "../ProfileContext";
import type { GapscanConfig, GapscanStatus, LibraryItem } from "../api/types";

const CONFIGURED: GapscanConfig = {
  profile: "c411",
  tracker_configured: true,
  tracker_base_url: "https://c411.org",
  sonarr_configured: false,
  sonarr_url: null,
  radarr_configured: true,
  radarr_url: "http://radarr.local:7878",
  sonarr_path_mappings: {},
  radarr_path_mappings: {},
  tracker_announce_url_configured: false,
  staging_dir: null,
};

const IDLE_STATUS: GapscanStatus = {
  state: "idle", total: 0, processed: 0, started_at: null, finished_at: null, error: null,
};

/** Titre deja verifie sur le tracker (statut connu). */
const MATRIX_ITEM: LibraryItem = {
  media_type: "movie", title: "Matrix", year: 1999, season_number: null,
  imdb_id: "tt0133093", tvdb_id: null, tmdb_id: "603", genres: ["Action"], added_at: null,
  local_quality: { raw: "", resolution: 2160, source: "BLURAY", codec: "X265", languages: ["VFF"], multi: true, pure: false },
  radarr_movie_id: null, sonarr_series_id: null, already_processed: false, last_processed_at: null,
  key: '["movie","tt0133093",1999]',
  status: "absent", checked_at: 1700000000, has_freeleech_alternative: false, has_double_upload_window: false,
  error: null, local_paths: [], path_resolved: true, path_error: null, tracker_genre: null,
};

/** Titre jamais scanne (statut inconnu) -- comportement d'origine de la
 * "Bibliotheque" avant la fusion. */
const SHOW_ITEM: LibraryItem = {
  media_type: "series", title: "Show", year: 2020, season_number: 1,
  imdb_id: null, tvdb_id: 99, tmdb_id: null, genres: ["Drama"], added_at: null,
  local_quality: { raw: "", resolution: 1080, source: null, codec: null, languages: [], multi: false, pure: false },
  radarr_movie_id: null, sonarr_series_id: 7, already_processed: false, last_processed_at: null,
  key: '["series",99,1]',
  status: null, checked_at: null, has_freeleech_alternative: false, has_double_upload_window: false,
  error: null, local_paths: [], path_resolved: false, path_error: null, tracker_genre: null,
};

function renderPage() {
  return render(
    <MemoryRouter>
      <ProfileProvider>
        <LibraryPage />
      </ProfileProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(gapscanConfig).mockResolvedValue(CONFIGURED);
  vi.mocked(gapscanStatus).mockResolvedValue(IDLE_STATUS);
  vi.mocked(libraryResults).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(listAllProfiles).mockResolvedValue({ c411: ["video"] });
  vi.mocked(readManagedProfile).mockResolvedValue({
    name: "c411", rules: { tracker: { display_name: "C411" } }, templates: {},
  });
});

afterEach(() => vi.resetAllMocks());

describe("LibraryPage", () => {
  it("n'a pas de selecteur de profil qui lui soit propre (vit dans l'entete, App.tsx)", async () => {
    renderPage();
    await screen.findByRole("button", { name: "Lancer un scan complet" });
    expect(screen.queryByRole("combobox", { name: /^profil/i })).not.toBeInTheDocument();
  });

  it("charge et affiche la bibliotheque au montage", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_ITEM], total: 1 });
    renderPage();
    expect(await screen.findByText(/Matrix \(1999\)/)).toBeInTheDocument();
    expect(libraryResults).toHaveBeenCalled();
  });

  it("affiche le statut tracker connu, avec ses badges", async () => {
    vi.mocked(libraryResults).mockResolvedValue({
      items: [{ ...MATRIX_ITEM, has_freeleech_alternative: true, has_double_upload_window: true }],
      total: 1,
    });
    renderPage();

    await screen.findByText(/Matrix \(1999\)/);
    const table = within(screen.getByRole("table"));
    expect(table.getByText("Absent de C411")).toBeInTheDocument();
    expect(table.getByText("FL")).toBeInTheDocument();
    expect(table.getByText("2x")).toBeInTheDocument();
    expect(table.getByText(/2160p.*BLURAY.*VFF/)).toBeInTheDocument();
  });

  it("affiche 'Non vérifié' pour un titre jamais scanne", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [SHOW_ITEM], total: 1 });
    renderPage();

    await screen.findByText(/Show \(2020\)/);
    const table = within(screen.getByRole("table"));
    expect(table.getByText("Non vérifié")).toBeInTheDocument();
  });

  it("n'affiche pas de badge de chemin pour un titre jamais scanne (path_resolved faux par defaut)", async () => {
    renderPage();
    vi.mocked(libraryResults).mockResolvedValue({ items: [SHOW_ITEM], total: 1 });
    // Le mock ci-dessus n'a d'effet qu'au prochain appel -- redeclenche un
    // chargement via un changement de filtre pour l'exercer proprement.
    await screen.findByRole("button", { name: "Lancer un scan complet" });
  });

  it("signale un chemin local non resolu par un badge UNIQUEMENT si deja scanne", async () => {
    vi.mocked(libraryResults).mockResolvedValue({
      items: [{ ...MATRIX_ITEM, path_resolved: false, path_error: "Fichier introuvable : /mnt/nas/Matrix.mkv" }],
      total: 1,
    });
    renderPage();

    const badge = await screen.findByTitle("Fichier introuvable : /mnt/nas/Matrix.mkv");
    expect(badge).toBeInTheDocument();
  });

  it("affiche un bouton Préparer l'upload sur une ligne avec chemin résolu, ouvre le panneau", async () => {
    const user = userEvent.setup();
    vi.mocked(libraryResults).mockResolvedValue({
      items: [{ ...MATRIX_ITEM, local_paths: ["/media/matrix.mkv"], path_resolved: true }],
      total: 1,
    });

    renderPage();

    const button = await screen.findByRole("button", { name: /Préparer l'upload/i });
    await user.click(button);

    expect(await screen.findByText("Panneau upload pour Matrix")).toBeInTheDocument();
  });

  it("transmet media_type/tmdb_id au panneau Préparer l'upload", async () => {
    const user = userEvent.setup();
    vi.mocked(libraryResults).mockResolvedValue({
      items: [{ ...MATRIX_ITEM, local_paths: ["/media/matrix.mkv"], path_resolved: true }],
      total: 1,
    });

    renderPage();
    await user.click(await screen.findByRole("button", { name: /Préparer l'upload/i }));

    expect(await screen.findByText("media_type=movie")).toBeInTheDocument();
    expect(await screen.findByText("tmdb_id=603")).toBeInTheDocument();
  });

  it("n'affiche pas de bouton Préparer l'upload si le chemin n'est pas résolu", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [SHOW_ITEM], total: 1 });
    renderPage();
    await screen.findByText(/Show \(2020\)/);
    expect(screen.queryByRole("button", { name: /Préparer l'upload/i })).not.toBeInTheDocument();
  });

  it("affiche l'encart Transferts en cours", async () => {
    renderPage();
    expect(await screen.findByText("Transferts en cours (mock)")).toBeInTheDocument();
  });

  // ------------------------------------------------------------------- //
  // Scan complet (bulk) -- ancien "Lancer un scan" de la page Scan C411.
  // ------------------------------------------------------------------- //
  it("chemin heureux : lancer un scan complet (deja termine au premier appel de statut) rafraichit la liste", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanRun).mockResolvedValue({ status: "started" });
    vi.mocked(gapscanStatus)
      .mockResolvedValueOnce(IDLE_STATUS)
      .mockResolvedValueOnce({ ...IDLE_STATUS, state: "done", total: 1, processed: 1 });
    vi.mocked(libraryResults)
      .mockResolvedValueOnce({ items: [], total: 0 })
      .mockResolvedValueOnce({ items: [MATRIX_ITEM], total: 1 });

    renderPage();
    await screen.findByRole("button", { name: "Lancer un scan complet" });

    await user.click(screen.getByRole("button", { name: "Lancer un scan complet" }));

    expect(gapscanRun).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/Matrix \(1999\)/)).toBeInTheDocument();
    expect(screen.queryByText(/titres traités/)).not.toBeInTheDocument();
  });

  it("scan en erreur : message affiche", async () => {
    vi.mocked(gapscanStatus).mockResolvedValue({
      ...IDLE_STATUS, state: "error", error: "C411 injoignable (timeout)",
    });
    renderPage();
    expect(await screen.findByText(/C411 injoignable \(timeout\)/)).toBeInTheDocument();
  });

  it("service non configure : bouton desactive avec message explicite", async () => {
    vi.mocked(gapscanConfig).mockResolvedValue({
      profile: "c411", tracker_configured: false, tracker_base_url: null,
      sonarr_configured: false, sonarr_url: null, radarr_configured: false, radarr_url: null,
      sonarr_path_mappings: {}, radarr_path_mappings: {},
      tracker_announce_url_configured: false, staging_dir: null,
    });
    renderPage();

    expect(await screen.findByText(/Clé API C411 non configurée/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lancer un scan complet" })).toBeDisabled();
    expect(screen.getByLabelText("URL Sonarr")).toBeInTheDocument();
  });

  it("enregistre Sonarr via le formulaire de configuration", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanConfigWrite).mockResolvedValue({
      ...CONFIGURED, sonarr_configured: true, sonarr_url: "http://sonarr.local:8989",
    });

    renderPage();
    await user.click(await screen.findByRole("button", { name: /Configuration/ }));

    await user.type(screen.getByLabelText("URL Sonarr"), "http://sonarr.local:8989");
    await user.type(screen.getByLabelText("Clé API Sonarr"), "sk-123");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(gapscanConfigWrite).toHaveBeenCalledWith(
      {
        sonarr_url: "http://sonarr.local:8989",
        sonarr_api_key: "sk-123",
        radarr_url: "http://radarr.local:7878",
        tracker_base_url: "https://c411.org",
        sonarr_path_mappings: {},
        radarr_path_mappings: {},
      },
      "c411",
    );
    expect(await screen.findByText("Enregistré.")).toBeInTheDocument();
  });

  it("pas de scan precedent : pas de case 'Scan rapide', et le scan lance est complet", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanRun).mockResolvedValue({ status: "started" });

    renderPage();
    await screen.findByRole("button", { name: "Lancer un scan complet" });

    expect(screen.queryByText("Scan rapide")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Lancer un scan complet" }));
    expect(gapscanRun).toHaveBeenCalledWith(false, undefined, "c411");
  });

  it("scan precedent disponible : case 'Scan rapide' cochee par defaut, scan lance en mode incremental", async () => {
    const user = userEvent.setup();
    const DONE_STATUS: GapscanStatus = { ...IDLE_STATUS, state: "done", total: 1, processed: 1, finished_at: 1700000000 };
    vi.mocked(gapscanStatus).mockResolvedValue(DONE_STATUS);
    vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_ITEM], total: 1 });
    vi.mocked(gapscanRun).mockResolvedValue({ status: "started" });

    renderPage();
    const checkbox = await screen.findByRole("checkbox", { name: "Scan rapide" });
    expect(checkbox).toBeChecked();

    await user.click(screen.getByRole("button", { name: "Lancer un scan complet" }));
    expect(gapscanRun).toHaveBeenCalledWith(true, undefined, "c411");
  });

  it("selectionner 'Films seulement' passe only='movies' a gapscanRun", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanRun).mockResolvedValue({ status: "started" });

    renderPage();
    await screen.findByRole("button", { name: "Lancer un scan complet" });

    await user.selectOptions(screen.getByRole("combobox", { name: "Bibliothèque à scanner" }), "movies");
    await user.click(screen.getByRole("button", { name: "Lancer un scan complet" }));

    expect(gapscanRun).toHaveBeenCalledWith(false, "movies", "c411");
  });

  // ------------------------------------------------------------------- //
  // Selection + scan cible (ancienne page "Bibliotheque")
  // ------------------------------------------------------------------- //
  it("selectionner une ligne puis Verifier appelle gapscanRun avec la selection, sans naviguer ailleurs", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [SHOW_ITEM], total: 1 });
    vi.mocked(gapscanRun).mockResolvedValue({ status: "started" });
    const user = userEvent.setup();
    renderPage();

    await screen.findByText(/Show \(2020\)/);
    await user.click(screen.getByRole("checkbox", { name: /Show/i }));
    await user.click(screen.getByRole("button", { name: /Vérifier sur le tracker/i }));

    await waitFor(() => {
      expect(gapscanRun).toHaveBeenCalledWith(false, undefined, "c411", [SHOW_ITEM.key]);
    });
    // Toujours sur la meme page (plus de redirection vers /gapscan).
    expect(await screen.findByRole("button", { name: "Lancer un scan complet" })).toBeInTheDocument();
  });

  it("le bouton Verifier est desactive sans selection", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [SHOW_ITEM], total: 1 });
    renderPage();
    await screen.findByText(/Show \(2020\)/);
    expect(screen.getByRole("button", { name: /Vérifier sur le tracker/i })).toBeDisabled();
  });

  it("le filtre texte relance libraryResults avec q, revient a la page 1", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [], total: 0 });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(libraryResults).toHaveBeenCalled());

    await user.type(screen.getByLabelText(/Recherche/i), "matrix");
    await waitFor(() => {
      const lastCall = vi.mocked(libraryResults).mock.calls.at(-1)?.[0];
      expect(lastCall?.q).toBe("matrix");
      expect(lastCall?.page).toBe(1);
    });
  });

  it("le filtre Statut inclut 'Non vérifié' et le transmet a libraryResults", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [], total: 0 });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(libraryResults).toHaveBeenCalled());

    await user.selectOptions(screen.getByLabelText("Statut"), "not_verified");
    await waitFor(() => {
      expect(vi.mocked(libraryResults)).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "not_verified", page: 1 }),
      );
    });
  });

  it("le filtre Genre tracker (distinct du Genre bibliotheque) est transmis a libraryResults", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [], total: 0 });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(libraryResults).toHaveBeenCalled());

    await user.selectOptions(screen.getByLabelText("Genre tracker"), "anime");
    await waitFor(() => {
      expect(vi.mocked(libraryResults)).toHaveBeenLastCalledWith(
        expect.objectContaining({ trackerGenre: "anime", page: 1 }),
      );
    });
  });

  it("affiche la pagination et change de page au clic sur Suivant", async () => {
    const user = userEvent.setup();
    vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_ITEM], total: 120 });

    renderPage();
    await screen.findByText(/Page 1 \/ 3/);

    await user.click(screen.getByRole("button", { name: "Suivant" }));

    await waitFor(() => {
      expect(libraryResults).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }));
    });
  });
});
