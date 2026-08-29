import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import UploadPrepPanel from "./UploadPrepPanel";
import { ProfileProvider } from "../ProfileContext";

vi.mock("../api/client", () => ({
  prepareUploadPreview: vi.fn(),
  prepareUploadCommit: vi.fn(),
  listAllProfiles: vi.fn(),
  readManagedProfile: vi.fn(),
}));

import {
  listAllProfiles,
  prepareUploadCommit,
  prepareUploadPreview,
  readManagedProfile,
} from "../api/client";
import { ApiError } from "../api/types";
import type { UploadGroupProposal } from "../api/types";

function renderPanel(props: { localPaths: string[]; title: string; onClose: () => void }) {
  return render(
    <ProfileProvider>
      <UploadPrepPanel {...props} />
    </ProfileProvider>,
  );
}

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
  vi.mocked(listAllProfiles).mockResolvedValue({ c411: ["video"], ygg: ["video"] });
  vi.mocked(readManagedProfile).mockResolvedValue({
    name: "c411", rules: { tracker: { display_name: "C411" } }, templates: {},
  });
});

afterEach(() => vi.restoreAllMocks());

it("charge et affiche l'apercu au montage avec le titre deja connu (GapResult) comme override par defaut", async () => {
  /* Cas reel signale par l'utilisateur (2026-08-28, "Les Fils du vent") :
   * le titre Radarr/Sonarr est deja affiche dans l'en-tete du panneau --
   * jamais reutilise jusqu'ici pour le nommage, qui redecouvrait un titre
   * (souvent anglais) depuis le nom de fichier au lieu de ca. */
  vi.mocked(prepareUploadPreview).mockResolvedValue(ONE_GROUP);
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });

  await waitFor(() => {
    expect(screen.getByText(/Movie\.2020\.MULTI\.VFF\.1080p\.BluRay\.AC3\.x264-TEAM$/)).toBeInTheDocument();
  });
  expect(prepareUploadPreview).toHaveBeenCalledWith(["/media/movie.mkv"], "c411", "Movie");
  expect(screen.getByLabelText(/Titre/i)).toHaveValue("Movie");
});

it("un groupe bloque n'a pas de bouton Confirmer, affiche l'avertissement", async () => {
  vi.mocked(prepareUploadPreview).mockResolvedValue(BLOCKED_GROUP);
  renderPanel({ localPaths: ["/media/x.mkv"], title: "X", onClose: vi.fn() });

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
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });

  await waitFor(() => screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(screen.getByRole("button", { name: /Confirmer/i }));

  await waitFor(() => {
    expect(screen.getByText(/staging\/Movie\.2020\.MULTI\.VFF\.1080p\.BluRay\.AC3\.x264-TEAM\.torrent/)).toBeInTheDocument();
  });
  expect(prepareUploadCommit).toHaveBeenCalledWith(
    "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM",
    ONE_GROUP[0].files,
    "c411",
  );
});

it("une erreur de chargement affiche un message", async () => {
  vi.mocked(prepareUploadPreview).mockRejectedValue(new ApiError(500, "Erreur interne du serveur."));
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });

  await waitFor(() => {
    expect(screen.getByText(/Erreur interne du serveur/)).toBeInTheDocument();
  });
});

it("Recalculer renvoie le titre corrige a prepareUploadPreview", async () => {
  const user = userEvent.setup();
  vi.mocked(prepareUploadPreview).mockResolvedValue(ONE_GROUP);
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });
  await waitFor(() => screen.getByRole("button", { name: "Recalculer" }));

  const CORRECTED_GROUP: UploadGroupProposal[] = [
    { ...ONE_GROUP[0], release_name: "Un.Gars.Une.Fille.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM" },
  ];
  vi.mocked(prepareUploadPreview).mockResolvedValue(CORRECTED_GROUP);

  await user.clear(screen.getByLabelText(/Titre/i));
  await user.type(screen.getByLabelText(/Titre/i), "Un Gars, Une Fille");
  await user.click(screen.getByRole("button", { name: "Recalculer" }));

  await waitFor(() => {
    expect(screen.getByText(/^Un\.Gars\.Une\.Fille\./)).toBeInTheDocument();
  });
  expect(prepareUploadPreview).toHaveBeenLastCalledWith(
    ["/media/movie.mkv"],
    "c411",
    "Un Gars, Une Fille",
  );
});

it("defaults to the globally active profile", async () => {
  vi.mocked(prepareUploadPreview).mockResolvedValue(ONE_GROUP);
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });

  await waitFor(() => {
    expect(prepareUploadPreview).toHaveBeenCalledWith(["/media/movie.mkv"], "c411", "Movie");
  });
});

it("lets the user override the profile for this one upload without changing the global active profile", async () => {
  const user = userEvent.setup();
  vi.mocked(prepareUploadPreview).mockResolvedValue(ONE_GROUP);
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });
  await waitFor(() => screen.getByRole("button", { name: "Recalculer" }));

  const select = screen.getByLabelText(/Profil pour cet upload/i);
  await user.selectOptions(select, "ygg");

  await waitFor(() => {
    expect(prepareUploadPreview).toHaveBeenLastCalledWith(["/media/movie.mkv"], "ygg", "Movie");
  });
});
