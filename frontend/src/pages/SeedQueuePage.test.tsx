import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  seedQueue: vi.fn(),
  addToSeedQueue: vi.fn(),
  seedStatus: vi.fn(),
}));

import { addToSeedQueue, seedQueue, seedStatus } from "../api/client";
import SeedQueuePage from "./SeedQueuePage";
import type { SeedingTorrent, SeedQueueEntry } from "../api/types";

const ENTRY: SeedQueueEntry = {
  key: '["movie",42]', media_type: "movie", release_name: "Movie.2020.1080p.x264-TEAM",
  staged_path: "/staging/Movie.2020.1080p.x264-TEAM.mkv", sent_at: 1700000000,
};

const TORRENT: SeedingTorrent = {
  name: "Series.S01.1080p.x264-TEAM", size: 4294967296, progress: 1.0,
  ratio: 1.42, state: "uploading", upspeed: 512000, added_on: 1700000000,
};

function renderPage() {
  return render(<SeedQueuePage />);
}

beforeEach(() => {
  vi.mocked(seedQueue).mockReset();
  vi.mocked(addToSeedQueue).mockReset();
  vi.mocked(seedStatus).mockReset();
  vi.mocked(seedStatus).mockResolvedValue([]);
});

describe("SeedQueuePage", () => {
  it("charge et affiche la file d'attente au montage", async () => {
    vi.mocked(seedQueue).mockResolvedValue([ENTRY]);
    renderPage();
    expect(await screen.findByText(/Movie\.2020\.1080p\.x264-TEAM/)).toBeInTheDocument();
  });

  it("liste vide : message explicite", async () => {
    vi.mocked(seedQueue).mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText(/Aucun titre en attente/i)).toBeInTheDocument();
  });

  it("depose un fichier puis clique Ajouter -- appelle addToSeedQueue, retire la ligne", async () => {
    vi.mocked(seedQueue).mockResolvedValue([ENTRY]);
    vi.mocked(addToSeedQueue).mockResolvedValue({ status: "added" });
    const user = userEvent.setup();
    renderPage();

    await screen.findByText(/Movie\.2020\.1080p\.x264-TEAM/);
    const file = new File([new Uint8Array([1, 2, 3])], "Movie.2020.1080p.x264-TEAM.torrent");
    const input = screen.getByLabelText(/torrent re-signé/i);
    await user.upload(input, file);
    await user.click(screen.getByRole("button", { name: /Ajouter au client de seed/i }));

    await waitFor(() => {
      expect(addToSeedQueue).toHaveBeenCalledWith(ENTRY.key, file);
    });
    await waitFor(() => {
      expect(screen.queryByText(/Movie\.2020\.1080p\.x264-TEAM/)).not.toBeInTheDocument();
    });
  });

  it("erreur d'ajout : message affiche, la ligne reste presente", async () => {
    vi.mocked(seedQueue).mockResolvedValue([ENTRY]);
    vi.mocked(addToSeedQueue).mockRejectedValue(new Error("qBittorrent injoignable"));
    const user = userEvent.setup();
    renderPage();

    await screen.findByText(/Movie\.2020\.1080p\.x264-TEAM/);
    const file = new File([new Uint8Array([1, 2, 3])], "Movie.2020.1080p.x264-TEAM.torrent");
    await user.upload(screen.getByLabelText(/torrent re-signé/i), file);
    await user.click(screen.getByRole("button", { name: /Ajouter au client de seed/i }));

    expect(await screen.findByText(/injoignable/i)).toBeInTheDocument();
    expect(screen.getByText(/Movie\.2020\.1080p\.x264-TEAM/)).toBeInTheDocument();
  });

  it("le bouton Ajouter est desactive sans fichier choisi", async () => {
    vi.mocked(seedQueue).mockResolvedValue([ENTRY]);
    renderPage();
    await screen.findByText(/Movie\.2020\.1080p\.x264-TEAM/);
    expect(screen.getByRole("button", { name: /Ajouter au client de seed/i })).toBeDisabled();
  });
});

describe("SeedQueuePage -- section « En cours de seed » (retour utilisateur, 2026-09-06)", () => {
  it("charge et affiche les torrents actuellement en seed", async () => {
    vi.mocked(seedQueue).mockResolvedValue([]);
    vi.mocked(seedStatus).mockResolvedValue([TORRENT]);
    renderPage();

    expect(await screen.findByText(/Series\.S01\.1080p\.x264-TEAM/)).toBeInTheDocument();
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.getByText("1.42")).toBeInTheDocument();
    expect(screen.getByText("uploading")).toBeInTheDocument();
  });

  it("aucun torrent en seed : message explicite", async () => {
    vi.mocked(seedQueue).mockResolvedValue([]);
    vi.mocked(seedStatus).mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText(/Aucun torrent en seed actuellement/i)).toBeInTheDocument();
  });

  it("erreur qBittorrent : message affiche, ne bloque pas le reste de la page", async () => {
    vi.mocked(seedQueue).mockResolvedValue([ENTRY]);
    vi.mocked(seedStatus).mockRejectedValue(new Error("qBittorrent non configuré"));
    renderPage();

    expect(await screen.findByText(/qBittorrent non configuré/i)).toBeInTheDocument();
    expect(screen.getByText(/Movie\.2020\.1080p\.x264-TEAM/)).toBeInTheDocument();
  });
});
