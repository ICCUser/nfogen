import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GapScanPage from "./GapScanPage";

vi.mock("../api/client", () => ({
  downloadBlob: vi.fn(),
  gapscanConfig: vi.fn(),
  gapscanExportCsv: vi.fn(),
  gapscanResults: vi.fn(),
  gapscanRun: vi.fn(),
  gapscanStatus: vi.fn(),
}));

import {
  gapscanConfig,
  gapscanResults,
  gapscanRun,
  gapscanStatus,
} from "../api/client";
import type { GapResult, GapscanConfig, GapscanStatus } from "../api/types";

const CONFIGURED: GapscanConfig = {
  c411_configured: true,
  sonarr_configured: false,
  radarr_configured: true,
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
  local_quality: { raw: "", resolution: 2160, source: "BLURAY", codec: "X265", languages: ["VFF"], multi: true, pure: false },
  c411_matches: [],
  has_freeleech_alternative: false,
  has_double_upload_window: false,
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
  vi.mocked(gapscanResults).mockResolvedValue([]);
});

afterEach(() => vi.resetAllMocks());

describe("GapScanPage", () => {
  it("affiche les resultats deja disponibles au chargement, avec leur statut", async () => {
    vi.mocked(gapscanResults).mockResolvedValue([MATRIX_GAP]);

    renderPage();

    expect(await screen.findByText(/Matrix \(1999\)/)).toBeInTheDocument();
    // "Absent de C411" apparait aussi dans le select de filtre : on cible
    // le tableau pour ne pas ambiguer les deux occurrences.
    const table = within(screen.getByRole("table"));
    expect(table.getByText("Absent de C411")).toBeInTheDocument();
    expect(table.getByText(/2160p.*BLURAY.*VFF/)).toBeInTheDocument();
  });

  it("chemin heureux : lancer un scan (deja termine au premier appel de statut) affiche les resultats", async () => {
    const user = userEvent.setup();
    vi.mocked(gapscanRun).mockResolvedValue({ status: "started" });
    // Le premier appel a gapscanStatus (au montage) renvoie idle ; celui
    // declenche par le clic sur "Lancer un scan" renvoie deja "done".
    vi.mocked(gapscanStatus)
      .mockResolvedValueOnce(IDLE_STATUS)
      .mockResolvedValueOnce({ ...IDLE_STATUS, state: "done", total: 1, processed: 1 });
    vi.mocked(gapscanResults).mockResolvedValueOnce([]).mockResolvedValueOnce([MATRIX_GAP]);

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
      sonarr_configured: false,
      radarr_configured: false,
    });

    renderPage();

    expect(await screen.findByText(/NFOGEN_C411_API_KEY/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lancer un scan" })).toBeDisabled();
  });
});
