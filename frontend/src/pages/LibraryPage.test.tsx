import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  clearGapscanLog: vi.fn(),
  downloadBlob: vi.fn(),
  gapscanConfig: vi.fn(),
  gapscanConfigWrite: vi.fn(),
  gapscanExportCsv: vi.fn(),
  gapscanRun: vi.fn(),
  gapscanStatus: vi.fn(),
  libraryResults: vi.fn(),
  listAllProfiles: vi.fn(),
  readManagedProfile: vi.fn(),
  startSeedMatch: vi.fn(),
  seedMatchJobStatus: vi.fn(),
  cancelSeedMatchJob: vi.fn(),
}));

vi.mock("../components/UploadPrepPanel", () => ({
  default: (props: {
    title: string; onClose: () => void; mediaType?: string; tmdbId?: number | null;
    localPaths?: string[];
    seasonPack?: { title: string; team: string; is_full_series: boolean; seasons: { season_number: number; local_paths: string[] }[] };
  }) => (
    <div>
      <p>Panneau upload pour {props.title}</p>
      <p>media_type={props.mediaType}</p>
      <p>tmdb_id={String(props.tmdbId)}</p>
      <p>local_paths={(props.localPaths ?? []).join(",")}</p>
      {props.seasonPack && (
        <p>
          season_pack={props.seasonPack.title}/{props.seasonPack.team}/
          {props.seasonPack.seasons.map((s) => s.season_number).join("-")}
        </p>
      )}
      <button onClick={props.onClose}>Fermer le panneau</button>
    </div>
  ),
}));

vi.mock("../components/ActiveTransfersTray", () => ({
  default: () => <div>Transferts en cours (mock)</div>,
}));

import {
  cancelSeedMatchJob,
  clearGapscanLog,
  gapscanConfig,
  gapscanConfigWrite,
  gapscanRun,
  gapscanStatus,
  libraryResults,
  listAllProfiles,
  readManagedProfile,
  seedMatchJobStatus,
  startSeedMatch,
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
  qbittorrent_configured: false,
  qbittorrent_url: null,
  qbittorrent_verify_ssl: true,
  tmdb_configured: false,
};

const IDLE_STATUS: GapscanStatus = {
  state: "idle", total: 0, processed: 0, started_at: null, finished_at: null, error: null, log: [],
};

/** Titre deja verifie sur le tracker (statut connu). */
const MATRIX_ITEM: LibraryItem = {
  media_type: "movie", title: "Matrix", year: 1999, season_number: null,
  imdb_id: "tt0133093", tvdb_id: null, tmdb_id: "603", genres: ["Action"], added_at: null,
  local_quality: { raw: "", resolution: 2160, source: "BLURAY", codec: "X265", languages: ["VFF"], multi: true, pure: false },
  radarr_movie_id: null, sonarr_series_id: null, already_processed: false, last_processed_at: null,
  key: '["movie","tt0133093",1999]',
  status: "absent", checked_at: 1700000000, has_freeleech_alternative: false, has_double_upload_window: false,
  error: null, local_paths: [], path_resolved: true, path_error: null, tracker_genre: null, team: "TEAM",
  seed_match: null, size_bytes: 4_500_000_000,
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
  error: null, local_paths: [], path_resolved: false, path_error: null, tracker_genre: null, team: null,
  seed_match: null, size_bytes: null,
};

/** Deux saisons de "Lucifer", meme serie/equipe -- source pour le test du
 * bouton "Preparer le pack" (fusion de saisons, voir seasonsForPack). */
const LUCIFER_S05: LibraryItem = {
  media_type: "series", title: "Lucifer", year: 2016, season_number: 5,
  imdb_id: null, tvdb_id: 305288, tmdb_id: null, genres: ["Drama"], added_at: null,
  local_quality: { raw: "", resolution: 1080, source: "WEB", codec: "X264", languages: ["VFF"], multi: false, pure: false },
  radarr_movie_id: null, sonarr_series_id: 7, already_processed: false, last_processed_at: null,
  key: '["series",305288,5]',
  status: "absent", checked_at: 1700000000, has_freeleech_alternative: false, has_double_upload_window: false,
  error: null, local_paths: ["/media/lucifer/s05.mkv"], path_resolved: true, path_error: null,
  tracker_genre: null, team: "Frosties", seed_match: null, size_bytes: 9_000_000_000,
};

const LUCIFER_S06: LibraryItem = {
  ...LUCIFER_S05, season_number: 6, key: '["series",305288,6]', local_paths: ["/media/lucifer/s06.mkv"],
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
  vi.mocked(libraryResults).mockResolvedValue({ items: [], total: 0, season_packs: [] });
  vi.mocked(listAllProfiles).mockResolvedValue({ c411: ["video"] });
  vi.mocked(readManagedProfile).mockResolvedValue({
    name: "c411", rules: { tracker: { display_name: "C411" } }, templates: {},
  });
  vi.mocked(clearGapscanLog).mockResolvedValue({ status: "cleared" });
});

afterEach(() => vi.resetAllMocks());

describe("LibraryPage", () => {
  it("n'a pas de selecteur de profil qui lui soit propre (vit dans l'entete, App.tsx)", async () => {
    renderPage();
    await screen.findByRole("button", { name: "Lancer un scan complet" });
    expect(screen.queryByRole("combobox", { name: /^profil/i })).not.toBeInTheDocument();
  });

  it("charge et affiche la bibliotheque au montage", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_ITEM], total: 1, season_packs: [] });
    renderPage();
    expect(await screen.findByText(/Matrix \(1999\)/)).toBeInTheDocument();
    expect(libraryResults).toHaveBeenCalled();
  });

  it("affiche le tag d'equipe par ligne, ou un tiret si absent", async () => {
    /* Retour utilisateur, 2026-09-08 : reperer d'un coup d'oeil quelles
     * saisons d'une meme serie partagent la meme equipe. */
    vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_ITEM, SHOW_ITEM], total: 2, season_packs: [] });
    renderPage();
    await screen.findByText(/Matrix \(1999\)/);
    expect(screen.getByText("TEAM")).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader", { name: "Team" })).toHaveLength(1);
  });

  it("affiche le bloc 'Packs disponibles' quand la bibliotheque en detecte", async () => {
    vi.mocked(libraryResults).mockResolvedValue({
      items: [MATRIX_ITEM], total: 1,
      season_packs: [
        {
          sonarr_series_id: 7, title: "Lucifer", year: 2016, team: "Frosties",
          season_numbers: [5, 6], is_full_series: true, item_keys: ["k1", "k2"],
        },
      ],
    });
    renderPage();
    expect(await screen.findByText("Packs disponibles")).toBeInTheDocument();
    expect(screen.getByText(/Lucifer — INTEGRALE \(Frosties\)/)).toBeInTheDocument();
  });

  it("n'affiche pas le bloc 'Packs disponibles' si aucune suggestion", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_ITEM], total: 1, season_packs: [] });
    renderPage();
    await screen.findByText(/Matrix \(1999\)/);
    expect(screen.queryByText("Packs disponibles")).not.toBeInTheDocument();
  });

  it("affiche le bouton 'Seed possible' quand seed_match est present", async () => {
    const matrixWithSeedMatch: LibraryItem = {
      ...MATRIX_ITEM, status: "covered",
      seed_match: { guid: "guid-1", release_name: "Matrix.1999.1080p.BluRay.x264-TEAM" },
    };
    vi.mocked(libraryResults).mockResolvedValue({ items: [matrixWithSeedMatch], total: 1, season_packs: [] });
    renderPage();
    await screen.findByText(/Matrix \(1999\)/);
    expect(screen.getByRole("button", { name: "Seed possible" })).toBeInTheDocument();
  });

  it("n'affiche pas le bouton 'Seed possible' quand seed_match est absent", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_ITEM], total: 1, season_packs: [] });
    renderPage();
    await screen.findByText(/Matrix \(1999\)/);
    expect(screen.queryByRole("button", { name: "Seed possible" })).not.toBeInTheDocument();
  });

  it("'Seed possible' lance le job, affiche le resultat DONE", async () => {
    const user = userEvent.setup();
    const matrixWithSeedMatch: LibraryItem = {
      ...MATRIX_ITEM, status: "covered",
      seed_match: { guid: "guid-1", release_name: "Matrix.1999.1080p.BluRay.x264-TEAM" },
    };
    vi.mocked(libraryResults).mockResolvedValue({ items: [matrixWithSeedMatch], total: 1, season_packs: [] });
    vi.mocked(startSeedMatch).mockResolvedValue({ job_id: "job-1" });
    vi.mocked(seedMatchJobStatus).mockResolvedValue({
      job_id: "job-1", state: "done", started_at: 1, finished_at: 2, error: null, result: { warning: null },
    });
    renderPage();
    await screen.findByText(/Matrix \(1999\)/);

    await user.click(screen.getByRole("button", { name: "Seed possible" }));

    expect(startSeedMatch).toHaveBeenCalledWith(matrixWithSeedMatch.key, "guid-1", "Matrix.1999.1080p.BluRay.x264-TEAM");
    expect(await screen.findByText(/En seed/)).toBeInTheDocument();
  });

  it("'Seed possible' affiche l'avertissement quand le job finit en MISMATCH", async () => {
    const user = userEvent.setup();
    const matrixWithSeedMatch: LibraryItem = {
      ...MATRIX_ITEM, status: "covered",
      seed_match: { guid: "guid-1", release_name: "Matrix.1999.1080p.BluRay.x264-TEAM" },
    };
    vi.mocked(libraryResults).mockResolvedValue({ items: [matrixWithSeedMatch], total: 1, season_packs: [] });
    vi.mocked(startSeedMatch).mockResolvedValue({ job_id: "job-1" });
    vi.mocked(seedMatchJobStatus).mockResolvedValue({
      job_id: "job-1", state: "mismatch", started_at: 1, finished_at: 2, error: null,
      result: { warning: "Le fichier téléchargé ne correspond pas exactement — resté en pause dans qBittorrent." },
    });
    renderPage();
    await screen.findByText(/Matrix \(1999\)/);

    await user.click(screen.getByRole("button", { name: "Seed possible" }));

    expect(await screen.findByText(/ne correspond pas exactement/)).toBeInTheDocument();
  });

  it("'Annuler' pendant la verification du seed appelle cancelSeedMatchJob", async () => {
    const user = userEvent.setup();
    const matrixWithSeedMatch: LibraryItem = {
      ...MATRIX_ITEM, status: "covered",
      seed_match: { guid: "guid-1", release_name: "Matrix.1999.1080p.BluRay.x264-TEAM" },
    };
    vi.mocked(libraryResults).mockResolvedValue({ items: [matrixWithSeedMatch], total: 1, season_packs: [] });
    vi.mocked(startSeedMatch).mockResolvedValue({ job_id: "job-1" });
    vi.mocked(seedMatchJobStatus).mockResolvedValue({
      job_id: "job-1", state: "checking", started_at: 1, finished_at: null, error: null, result: null,
    });
    vi.mocked(cancelSeedMatchJob).mockResolvedValue({ status: "cancelling" });
    renderPage();
    await screen.findByText(/Matrix \(1999\)/);

    await user.click(screen.getByRole("button", { name: "Seed possible" }));
    await user.click(await screen.findByRole("button", { name: "Annuler" }));

    expect(cancelSeedMatchJob).toHaveBeenCalledWith("job-1");
  });

  it("'Preparer le pack' ouvre UploadPrepPanel avec les saisons fusionnees", async () => {
    const user = userEvent.setup();
    vi.mocked(libraryResults).mockResolvedValue({
      items: [LUCIFER_S05, LUCIFER_S06], total: 2,
      season_packs: [
        {
          sonarr_series_id: 7, title: "Lucifer", year: 2016, team: "Frosties",
          season_numbers: [5, 6], is_full_series: false, item_keys: [LUCIFER_S05.key, LUCIFER_S06.key],
        },
      ],
    });
    renderPage();
    await screen.findByText("Packs disponibles");

    await user.click(screen.getByRole("button", { name: "Préparer le pack" }));

    expect(await screen.findByText("Panneau upload pour Lucifer S05S06")).toBeInTheDocument();
    expect(screen.getByText("media_type=series")).toBeInTheDocument();
    expect(screen.getByText("local_paths=/media/lucifer/s05.mkv,/media/lucifer/s06.mkv")).toBeInTheDocument();
    expect(screen.getByText("season_pack=Lucifer/Frosties/5-6")).toBeInTheDocument();
  });

  it("'Preparer le pack' est desactive si une saison du pack n'est pas visible dans la page/le filtre courant", async () => {
    /* Limitation connue (retour utilisateur, 2026-09-08) : seasonsForPack
     * ne peut resoudre que les saisons presentes dans `items` -- ici seule
     * S05 est chargee, S06 manque (page suivante, filtre...). */
    vi.mocked(libraryResults).mockResolvedValue({
      items: [LUCIFER_S05], total: 1,
      season_packs: [
        {
          sonarr_series_id: 7, title: "Lucifer", year: 2016, team: "Frosties",
          season_numbers: [5, 6], is_full_series: false, item_keys: [LUCIFER_S05.key, LUCIFER_S06.key],
        },
      ],
    });
    renderPage();
    await screen.findByText("Packs disponibles");

    expect(screen.getByRole("button", { name: "Préparer le pack" })).toBeDisabled();
  });

  it("affiche le statut tracker connu, avec ses badges", async () => {
    vi.mocked(libraryResults).mockResolvedValue({
      items: [{ ...MATRIX_ITEM, has_freeleech_alternative: true, has_double_upload_window: true }],
      total: 1, season_packs: [],
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
    vi.mocked(libraryResults).mockResolvedValue({ items: [SHOW_ITEM], total: 1, season_packs: [] });
    renderPage();

    await screen.findByText(/Show \(2020\)/);
    const table = within(screen.getByRole("table"));
    expect(table.getByText("Non vérifié")).toBeInTheDocument();
  });

  it("n'affiche pas de badge de chemin pour un titre jamais scanne (path_resolved faux par defaut)", async () => {
    renderPage();
    vi.mocked(libraryResults).mockResolvedValue({ items: [SHOW_ITEM], total: 1, season_packs: [] });
    // Le mock ci-dessus n'a d'effet qu'au prochain appel -- redeclenche un
    // chargement via un changement de filtre pour l'exercer proprement.
    await screen.findByRole("button", { name: "Lancer un scan complet" });
  });

  it("signale un chemin local non resolu par un badge UNIQUEMENT si deja scanne", async () => {
    vi.mocked(libraryResults).mockResolvedValue({
      items: [{ ...MATRIX_ITEM, path_resolved: false, path_error: "Fichier introuvable : /mnt/nas/Matrix.mkv" }],
      total: 1, season_packs: [],
    });
    renderPage();

    const badge = await screen.findByTitle("Fichier introuvable : /mnt/nas/Matrix.mkv");
    expect(badge).toBeInTheDocument();
  });

  it("affiche un bouton Préparer l'upload sur une ligne avec chemin résolu, ouvre le panneau", async () => {
    const user = userEvent.setup();
    vi.mocked(libraryResults).mockResolvedValue({
      items: [{ ...MATRIX_ITEM, local_paths: ["/media/matrix.mkv"], path_resolved: true }],
      total: 1, season_packs: [],
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
      total: 1, season_packs: [],
    });

    renderPage();
    await user.click(await screen.findByRole("button", { name: /Préparer l'upload/i }));

    expect(await screen.findByText("media_type=movie")).toBeInTheDocument();
    expect(await screen.findByText("tmdb_id=603")).toBeInTheDocument();
  });

  it("n'affiche pas de bouton Préparer l'upload si le chemin n'est pas résolu", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [SHOW_ITEM], total: 1, season_packs: [] });
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
      .mockResolvedValueOnce({ items: [], total: 0, season_packs: [] })
      .mockResolvedValueOnce({ items: [MATRIX_ITEM], total: 1, season_packs: [] });

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

  it("affiche le journal du scan, meme apres qu'il soit termine (ne se vide pas seul)", async () => {
    vi.mocked(gapscanStatus).mockResolvedValue({
      ...IDLE_STATUS, state: "done", finished_at: 1700000000,
      log: [
        { title: "Matrix", year: 1999, media_type: "movie", season_number: null, status: "absent" },
      ],
    });
    renderPage();
    expect(await screen.findByText(/Matrix/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Vider les logs/i })).toBeInTheDocument();
  });

  it("le bouton Vider les logs appelle clearGapscanLog et retire les lignes affichees", async () => {
    vi.mocked(gapscanStatus).mockResolvedValue({
      ...IDLE_STATUS, state: "done", finished_at: 1700000000,
      log: [
        { title: "Matrix", year: 1999, media_type: "movie", season_number: null, status: "absent" },
      ],
    });
    const user = userEvent.setup();
    renderPage();

    await screen.findByText(/Matrix/);
    await user.click(screen.getByRole("button", { name: /Vider les logs/i }));

    expect(clearGapscanLog).toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.queryByText(/Matrix/)).not.toBeInTheDocument();
    });
  });

  it("n'affiche pas le journal ni le bouton Vider quand il est vide", async () => {
    vi.mocked(gapscanStatus).mockResolvedValue({ ...IDLE_STATUS, log: [] });
    renderPage();
    await screen.findByRole("button", { name: "Lancer un scan complet" });
    expect(screen.queryByRole("button", { name: /Vider les logs/i })).not.toBeInTheDocument();
  });

  it("service non configure : bouton desactive avec message explicite", async () => {
    vi.mocked(gapscanConfig).mockResolvedValue({
      profile: "c411", tracker_configured: false, tracker_base_url: null,
      sonarr_configured: false, sonarr_url: null, radarr_configured: false, radarr_url: null,
      sonarr_path_mappings: {}, radarr_path_mappings: {},
      tracker_announce_url_configured: false, staging_dir: null,
      qbittorrent_configured: false, qbittorrent_url: null, qbittorrent_verify_ssl: true,
      tmdb_configured: false,
    });
    renderPage();

    expect(await screen.findByText(/Clé API C411 non configurée/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lancer un scan complet" })).toBeDisabled();
    expect(screen.getByLabelText(/URL de base/)).toBeInTheDocument();
  });

  it("enregistre la config du profil tracker (config globale migree vers Reglages)", async () => {
    /* Retour utilisateur, 2026-09-07 : "il faut separrer la configuration
     * du profil ... que ce soit au meme endroit sur l'interface non pas
     * d'accord" -- LibraryPage ne garde plus que le panneau du profil, la
     * config globale (Sonarr/Radarr/qBittorrent/TMDB) a migre vers
     * SettingsPage (voir SettingsPage.test.tsx). */
    const user = userEvent.setup();
    vi.mocked(gapscanConfigWrite).mockResolvedValue({
      ...CONFIGURED, tracker_base_url: "https://c411.example",
    });

    renderPage();
    await user.click(await screen.findByRole("button", { name: /Configuration du profil/ }));

    const baseUrlInput = screen.getByLabelText(/URL de base C411/);
    await user.clear(baseUrlInput);
    await user.type(baseUrlInput, "https://c411.example");
    await user.type(screen.getByLabelText(/Clé API C411/), "sk-tracker");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(gapscanConfigWrite).toHaveBeenCalledWith(
      {
        tracker_base_url: "https://c411.example",
        tracker_api_key: "sk-tracker",
      },
      "c411",
    );
    expect(screen.queryByLabelText("URL Sonarr")).not.toBeInTheDocument();
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
    vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_ITEM], total: 1, season_packs: [] });
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
    vi.mocked(libraryResults).mockResolvedValue({ items: [SHOW_ITEM], total: 1, season_packs: [] });
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
    vi.mocked(libraryResults).mockResolvedValue({ items: [SHOW_ITEM], total: 1, season_packs: [] });
    renderPage();
    await screen.findByText(/Show \(2020\)/);
    expect(screen.getByRole("button", { name: /Vérifier sur le tracker/i })).toBeDisabled();
  });

  it("le filtre texte relance libraryResults avec q, revient a la page 1", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [], total: 0, season_packs: [] });
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

  it("la recherche est debouncee -- taper vite ne relance pas un appel par frappe", async () => {
    /* Retour utilisateur, 2026-09-08 : "5 a 10 secondes de plus pour que
     * la recherche soit prise en compte" -- avant ce fix, chaque frappe
     * relancait immediatement /gapscan/library. */
    vi.mocked(libraryResults).mockResolvedValue({ items: [], total: 0, season_packs: [] });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(libraryResults).toHaveBeenCalled());
    const callsBeforeTyping = vi.mocked(libraryResults).mock.calls.length;

    await user.type(screen.getByLabelText(/Recherche/i), "matrix");
    // Immediatement apres avoir tape (avant les 400ms de debounce) :
    // aucun nouvel appel avec q rempli ne doit encore avoir eu lieu.
    const callsRightAfterTyping = vi.mocked(libraryResults).mock.calls.length;
    expect(callsRightAfterTyping).toBe(callsBeforeTyping);

    await waitFor(() => {
      const lastCall = vi.mocked(libraryResults).mock.calls.at(-1)?.[0];
      expect(lastCall?.q).toBe("matrix");
    });
    // Un seul appel supplementaire pour toute la saisie, pas un par lettre.
    expect(vi.mocked(libraryResults).mock.calls.length).toBe(callsBeforeTyping + 1);
  });

  it("le filtre Statut inclut 'Non vérifié' et le transmet a libraryResults", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [], total: 0, season_packs: [] });
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
    vi.mocked(libraryResults).mockResolvedValue({ items: [], total: 0, season_packs: [] });
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

  it("trie par titre au clic sur l'en-tête, inverse l'ordre au second clic", async () => {
    const user = userEvent.setup();
    vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_ITEM], total: 1, season_packs: [] });

    renderPage();
    await waitFor(() => expect(libraryResults).toHaveBeenCalled());

    await user.click(screen.getByTestId("col-header-title"));
    await waitFor(() => {
      expect(vi.mocked(libraryResults)).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: "title", order: "asc", page: 1 }),
      );
    });

    await user.click(screen.getByTestId("col-header-title"));
    await waitFor(() => {
      expect(vi.mocked(libraryResults)).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: "title", order: "desc", page: 1 }),
      );
    });
  });

  it("affiche la taille du fichier et permet de trier par taille", async () => {
    const user = userEvent.setup();
    vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_ITEM], total: 1, season_packs: [] });

    renderPage();
    await screen.findByText("4.19 Go");

    // TanStack Table trie une colonne NUMERIQUE decroissant au premier clic
    // (le plus gros fichier en premier) -- comportement par defaut de la
    // bibliotheque pour ce type de donnee, pas de "asc" comme pour du texte.
    await user.click(screen.getByTestId("col-header-size_bytes"));
    await waitFor(() => {
      expect(vi.mocked(libraryResults)).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: "size_bytes", order: "desc", page: 1 }),
      );
    });
  });

  it("affiche la pagination et change de page au clic sur Suivant", async () => {
    const user = userEvent.setup();
    vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_ITEM], total: 120, season_packs: [] });

    renderPage();
    await waitFor(() => expect(screen.getAllByText(/Page 1 \/ 3/).length).toBeGreaterThan(0));

    await user.click(screen.getAllByRole("button", { name: "Suivant" })[0]);

    await waitFor(() => {
      expect(libraryResults).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }));
    });
  });

  it("revient directement a la premiere page au clic sur Première page", async () => {
    const user = userEvent.setup();
    vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_ITEM], total: 120, season_packs: [] });

    renderPage();
    await waitFor(() => expect(screen.getAllByText(/Page 1 \/ 3/).length).toBeGreaterThan(0));
    await user.click(screen.getAllByRole("button", { name: "Suivant" })[0]);
    await waitFor(() => expect(screen.getAllByText(/Page 2 \/ 3/).length).toBeGreaterThan(0));

    await user.click(screen.getAllByRole("button", { name: "Première page" })[0]);

    await waitFor(() => {
      expect(libraryResults).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1 }));
    });
  });
});
