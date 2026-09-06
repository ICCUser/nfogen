import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  libraryResults: vi.fn(),
  gapscanRun: vi.fn(),
  listAllProfiles: vi.fn(),
  readManagedProfile: vi.fn(),
}));

import { gapscanRun, libraryResults, listAllProfiles, readManagedProfile } from "../api/client";
import LibraryPage from "./LibraryPage";
import { ProfileProvider } from "../ProfileContext";
import type { LibraryItem } from "../api/types";

const ITEM: LibraryItem = {
  media_type: "movie", title: "Movie", year: 2020, season_number: null,
  imdb_id: "tt001", tvdb_id: null, tmdb_id: "1", genres: ["Action"], added_at: null,
  local_quality: { raw: "", resolution: 1080, source: null, codec: null, languages: [], multi: false, pure: false },
  radarr_movie_id: 1, sonarr_series_id: null, already_processed: false, last_processed_at: null,
  key: '["movie","tt001",2020]',
};

function renderPage() {
  return render(
    <ProfileProvider>
      <MemoryRouter>
        <LibraryPage />
      </MemoryRouter>
    </ProfileProvider>,
  );
}

beforeEach(() => {
  vi.mocked(libraryResults).mockReset();
  vi.mocked(gapscanRun).mockReset();
  vi.mocked(listAllProfiles).mockResolvedValue({ c411: ["video"] });
  vi.mocked(readManagedProfile).mockResolvedValue({
    name: "c411", rules: { tracker: { display_name: "C411" } }, templates: {},
  });
});

describe("LibraryPage", () => {
  it("charge et affiche la bibliotheque au montage", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [ITEM], total: 1 });
    renderPage();
    await waitFor(() => expect(screen.getByText(/Movie/)).toBeInTheDocument());
    expect(libraryResults).toHaveBeenCalled();
  });

  it("selectionner une ligne puis lancer le scan appelle gapscanRun avec la selection", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [ITEM], total: 1 });
    vi.mocked(gapscanRun).mockResolvedValue({ status: "started" });
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => expect(screen.getByText(/Movie/)).toBeInTheDocument());
    await user.click(screen.getByRole("checkbox", { name: /Movie/i }));
    await user.click(screen.getByRole("button", { name: /Vérifier sur le tracker/i }));

    await waitFor(() => {
      expect(gapscanRun).toHaveBeenCalledWith(false, undefined, "c411", [ITEM.key]);
    });
  });

  it("le bouton de scan cible est desactive sans selection", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [ITEM], total: 1 });
    renderPage();
    await waitFor(() => expect(screen.getByText(/Movie/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Vérifier sur le tracker/i })).toBeDisabled();
  });

  it("le filtre texte relance libraryResults avec q", async () => {
    vi.mocked(libraryResults).mockResolvedValue({ items: [], total: 0 });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(libraryResults).toHaveBeenCalled());

    await user.type(screen.getByLabelText(/Recherche/i), "matrix");
    await waitFor(() => {
      const lastCall = vi.mocked(libraryResults).mock.calls.at(-1)?.[0];
      expect(lastCall?.q).toBe("matrix");
    });
  });
});
