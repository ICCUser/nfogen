import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GeneratePage from "./GeneratePage";

vi.mock("../api/client", () => ({
  listAllProfiles: vi.fn(),
  generateFromMetadata: vi.fn(),
  generateUpload: vi.fn(),
  proposeReleaseName: vi.fn(),
  downloadAsFile: vi.fn(),
}));
vi.mock("../lib/clientMediaInfo", () => ({
  extractVideoData: vi.fn(),
  extractGeneralTitles: vi.fn(),
}));

import {
  downloadAsFile,
  generateFromMetadata,
  generateUpload,
  listAllProfiles,
  proposeReleaseName,
} from "../api/client";
import { extractGeneralTitles, extractVideoData } from "../lib/clientMediaInfo";

const PROFILES = { c411: ["video", "audio", "game", "ebook", "print3d"] };

function videoFile(name = "film.mkv"): File {
  return new File(["binaire"], name, { type: "video/x-matroska" });
}

async function selectVideoFile(): Promise<void> {
  // Attend que les profils (charges de facon asynchrone au montage) soient
  // disponibles : sans "video" dans les options, la detection automatique de
  // categorie sur la selection du fichier ne positionnerait pas `category`.
  await screen.findByRole("option", { name: "video" });
  const input = screen.getByLabelText(/Fichier\(s\) source/) as HTMLInputElement;
  await userEvent.upload(input, videoFile());
}

beforeEach(() => {
  vi.mocked(listAllProfiles).mockResolvedValue(PROFILES);
  vi.mocked(downloadAsFile).mockImplementation(() => {});
  // Utilisee par l'effet de proposition de nom, declenche des qu'un fichier
  // est selectionne : neutre par defaut, pas l'objet de ces tests.
  vi.mocked(extractGeneralTitles).mockResolvedValue([null]);
  vi.mocked(proposeReleaseName).mockResolvedValue({ name: null, fields: {}, warnings: [] });
});

afterEach(() => vi.resetAllMocks());

describe("GeneratePage - generation video", () => {
  it("chemin heureux : extraction locale reussie -> generateFromMetadata, pas d'upload", async () => {
    vi.mocked(extractVideoData).mockResolvedValue({
      rawText: "General\nComplete name : film.mkv",
      metadata: [{ video_height: 1080, video_format: "AVC", audio_languages: ["fr"], subtitle_languages: [null] }],
    });
    vi.mocked(generateFromMetadata).mockResolvedValue({
      nfo: "General\nComplete name : film.mkv",
      warnings: [],
      filename: "Film.nfo",
    });

    render(<GeneratePage />);
    await selectVideoFile();

    await userEvent.click(screen.getByRole("button", { name: "Générer" }));

    expect(await screen.findByText(/Complete name/)).toBeInTheDocument();
    expect(generateFromMetadata).toHaveBeenCalledTimes(1);
    expect(generateUpload).not.toHaveBeenCalled();
    // Pas d'avertissement d'extraction quand elle a reussi.
    expect(
      screen.queryByText(/Extraction locale indisponible/),
    ).not.toBeInTheDocument();
  });

  it("repli sur upload : extraction locale en echec -> generateUpload, avertissement affiche", async () => {
    vi.mocked(extractVideoData).mockRejectedValue(new Error("WebAssembly indisponible"));
    vi.mocked(generateUpload).mockResolvedValue({
      nfo: "General\nComplete name : film.mkv (via upload)",
      warnings: [],
      filename: "Film.nfo",
    });

    render(<GeneratePage />);
    await selectVideoFile();

    await userEvent.click(screen.getByRole("button", { name: "Générer" }));

    expect(
      await screen.findByText(/Extraction locale indisponible.*envoi classique/),
    ).toBeInTheDocument();
    expect(await screen.findByText(/via upload/)).toBeInTheDocument();
    expect(generateUpload).toHaveBeenCalledTimes(1);
    expect(generateFromMetadata).not.toHaveBeenCalled();
  });
});
