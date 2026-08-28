import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import UploadPrepPanel from "./UploadPrepPanel";

vi.mock("../api/client", () => ({
  prepareUploadPreview: vi.fn(),
  prepareUploadCommit: vi.fn(),
}));

import { prepareUploadCommit, prepareUploadPreview } from "../api/client";
import { ApiError } from "../api/types";
import type { UploadGroupProposal } from "../api/types";

const ONE_GROUP: UploadGroupProposal[] = [
  {
    release_name: "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM",
    files: [
      { source_path: "/media/movie.mkv", staged_name: "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM.mkv" },
    ],
    warnings: [],
    blocked: false,
  },
];

const BLOCKED_GROUP: UploadGroupProposal[] = [
  { release_name: null, files: [], warnings: ["Aucune année ni tag de saison détecté."], blocked: true },
];

beforeEach(() => {
  vi.mocked(prepareUploadPreview).mockReset();
  vi.mocked(prepareUploadCommit).mockReset();
});

afterEach(() => vi.restoreAllMocks());

it("charge et affiche l'apercu au montage", async () => {
  vi.mocked(prepareUploadPreview).mockResolvedValue(ONE_GROUP);
  render(<UploadPrepPanel localPaths={["/media/movie.mkv"]} title="Movie" onClose={vi.fn()} />);

  await waitFor(() => {
    expect(screen.getByText(/Movie\.2020\.MULTI\.VFF\.1080p\.BluRay\.AC3\.x264-TEAM$/)).toBeInTheDocument();
  });
  expect(prepareUploadPreview).toHaveBeenCalledWith(["/media/movie.mkv"]);
});

it("un groupe bloque n'a pas de bouton Confirmer, affiche l'avertissement", async () => {
  vi.mocked(prepareUploadPreview).mockResolvedValue(BLOCKED_GROUP);
  render(<UploadPrepPanel localPaths={["/media/x.mkv"]} title="X" onClose={vi.fn()} />);

  await waitFor(() => {
    expect(screen.getByText(/Aucune année ni tag de saison/)).toBeInTheDocument();
  });
  expect(screen.queryByRole("button", { name: /Confirmer/i })).not.toBeInTheDocument();
});

it("Confirmer appelle prepareUploadCommit et affiche le resultat", async () => {
  vi.mocked(prepareUploadPreview).mockResolvedValue(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({
    release_name: "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM",
    staged_path: "/staging/Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM.mkv",
    torrent_path: "/staging/Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM.torrent",
    nfo_path: "/staging/Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM.nfo",
  });
  const user = userEvent.setup();
  render(<UploadPrepPanel localPaths={["/media/movie.mkv"]} title="Movie" onClose={vi.fn()} />);

  await waitFor(() => screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(screen.getByRole("button", { name: /Confirmer/i }));

  await waitFor(() => {
    expect(screen.getByText(/staging\/Movie\.2020\.MULTI\.VFF\.1080p\.BluRay\.AC3\.x264-TEAM\.torrent/)).toBeInTheDocument();
  });
  expect(prepareUploadCommit).toHaveBeenCalledWith(
    "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM",
    ONE_GROUP[0].files,
  );
});

it("une erreur de chargement affiche un message", async () => {
  vi.mocked(prepareUploadPreview).mockRejectedValue(new ApiError(500, "Erreur interne du serveur."));
  render(<UploadPrepPanel localPaths={["/media/movie.mkv"]} title="Movie" onClose={vi.fn()} />);

  await waitFor(() => {
    expect(screen.getByText(/Erreur interne du serveur/)).toBeInTheDocument();
  });
});
