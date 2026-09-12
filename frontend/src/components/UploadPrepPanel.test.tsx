import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import UploadPrepPanel from "./UploadPrepPanel";
import { ProfileProvider } from "../ProfileContext";

vi.mock("../api/client", () => ({
  prepareUploadPreview: vi.fn(),
  uploadPreviewJobStatus: vi.fn(),
  cancelUploadPreviewJob: vi.fn(),
  prepareUploadCommit: vi.fn(),
  commitJobStatus: vi.fn(),
  cancelCommitJob: vi.fn(),
  sendToTracker: vi.fn(),
  listAllProfiles: vi.fn(),
  readManagedProfile: vi.fn(),
  verifyIntegrity: vi.fn(),
  integrityJobStatus: vi.fn(),
  cancelIntegrityJob: vi.fn(),
}));

import {
  cancelCommitJob,
  cancelIntegrityJob,
  cancelUploadPreviewJob,
  commitJobStatus,
  integrityJobStatus,
  listAllProfiles,
  prepareUploadCommit,
  prepareUploadPreview,
  readManagedProfile,
  sendToTracker,
  uploadPreviewJobStatus,
  verifyIntegrity,
} from "../api/client";
import { ApiError } from "../api/types";
import type { SeasonPackRequest, UploadGroupProposal, UploadPreviewJob } from "../api/types";

/** Le calcul de l'apercu passe desormais par une tache de fond (retour
 * utilisateur, 2026-09-09) -- ce helper simule un job qui se termine
 * immediatement en "done" avec `groups` comme resultat, pour que les
 * tests existants (ecrits pour l'ancien appel synchrone) n'aient qu'a
 * remplacer `vi.mocked(prepareUploadPreview).mockResolvedValue(X)` par
 * `mockPreview(X)`. */
function mockPreview(groups: UploadGroupProposal[]): void {
  vi.mocked(prepareUploadPreview).mockResolvedValue({ job_id: "preview-job-1" });
  const job: UploadPreviewJob = {
    job_id: "preview-job-1", state: "done", processed: groups.length, total: groups.length,
    started_at: 0, finished_at: 1, error: null, result: groups,
  };
  vi.mocked(uploadPreviewJobStatus).mockResolvedValue(job);
}

function renderPanel(props: {
  localPaths: string[];
  title: string;
  onClose: () => void;
  mediaType?: "movie" | "series";
  radarrMovieId?: number | null;
  sonarrSeriesId?: number | null;
  tmdbId?: number | null;
  tvdbId?: number | null;
  genre?: "anime" | "documentaire" | null;
  seasonNumber?: number | null;
  seasonPack?: SeasonPackRequest;
}) {
  return render(
    <ProfileProvider>
      <UploadPrepPanel
        mediaType="movie"
        radarrMovieId={null}
        sonarrSeriesId={null}
        tmdbId={null}
        tvdbId={null}
        genre={null}
        seasonNumber={null}
        {...props}
      />
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

const DONE_JOB = {
  job_id: "job-1", release_name: "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM",
  state: "done" as const, percent: 100, started_at: 1000, finished_at: 1001, error: null,
  result: {
    release_name: "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM",
    staged_path: "/staging/Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM.mkv",
    torrent_path: "/staging/Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM.torrent",
    nfo_path: "/staging/Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM.nfo",
  },
};

beforeEach(() => {
  vi.mocked(prepareUploadPreview).mockReset();
  vi.mocked(uploadPreviewJobStatus).mockReset();
  vi.mocked(cancelUploadPreviewJob).mockReset();
  vi.mocked(prepareUploadCommit).mockReset();
  vi.mocked(commitJobStatus).mockReset();
  vi.mocked(cancelCommitJob).mockReset();
  vi.mocked(sendToTracker).mockReset();
  vi.mocked(verifyIntegrity).mockReset();
  vi.mocked(integrityJobStatus).mockReset();
  vi.mocked(cancelIntegrityJob).mockReset();
  vi.mocked(listAllProfiles).mockResolvedValue({ c411: ["video"], ygg: ["video"] });
  vi.mocked(readManagedProfile).mockResolvedValue({
    name: "c411", rules: { tracker: { display_name: "C411" } }, templates: {},
  });
});

afterEach(() => vi.restoreAllMocks());

it("la boite de dialogue reste bornee en hauteur, defilable en interne (incident reel, gros pack)", async () => {
  /* Retour utilisateur (2026-09-09, screenshot) : un gros pack (beaucoup
   * de fichiers listes) faisait grandir la boite de dialogue sans limite,
   * bien plus haut que l'ecran -- impossible de voir l'en-tete/le bouton
   * Fermer une fois scrolle au milieu de la liste. La boite doit rester
   * bornee (max-h) et defiler EN INTERNE (overflow-y-auto), pas grandir
   * indefiniment. */
  mockPreview(ONE_GROUP);
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });

  // Le plafonnement en hauteur/defilement interne vit desormais sur le
  // tiroir (Drawer) qui englobe la boite de dialogue, pas sur la boite
  // elle-meme (retour utilisateur, 2026-09-12 : conversion overlay -> tiroir).
  const dialog = await screen.findByRole("dialog");
  const drawerContent = dialog.parentElement as HTMLElement;
  expect(drawerContent.className).toContain("h-full");
  expect(drawerContent.className).toContain("overflow-y-auto");
});

it("charge et affiche l'apercu au montage avec le titre deja connu (GapResult) comme override par defaut", async () => {
  /* Cas reel signale par l'utilisateur (2026-08-28, "Les Fils du vent") :
   * le titre Radarr/Sonarr est deja affiche dans l'en-tete du panneau --
   * jamais reutilise jusqu'ici pour le nommage, qui redecouvrait un titre
   * (souvent anglais) depuis le nom de fichier au lieu de ca. */
  mockPreview(ONE_GROUP);
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });

  await waitFor(() => {
    expect(screen.getByText(/Movie\.2020\.MULTI\.VFF\.1080p\.BluRay\.AC3\.x264-TEAM$/)).toBeInTheDocument();
  });
  expect(prepareUploadPreview).toHaveBeenCalledWith(["/media/movie.mkv"], "c411", "Movie", undefined);
  expect(screen.getByLabelText(/Titre/i)).toHaveValue("Movie");
});

it("un groupe bloque n'a pas de bouton Confirmer, affiche l'avertissement", async () => {
  mockPreview(BLOCKED_GROUP);
  renderPanel({ localPaths: ["/media/x.mkv"], title: "X", onClose: vi.fn() });

  await waitFor(() => {
    expect(screen.getByText(/Aucune année ni tag de saison/)).toBeInTheDocument();
  });
  expect(screen.queryByRole("button", { name: /Confirmer/i })).not.toBeInTheDocument();
});

it("Confirmer demarre une tache, affiche le resultat une fois terminee (done)", async () => {
  mockPreview(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue(DONE_JOB);
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
    { mediaType: "movie", radarrMovieId: undefined, sonarrSeriesId: undefined, seasonNumber: undefined },
  );
  expect(commitJobStatus).toHaveBeenCalledWith("job-1");
});

it("affiche une barre de progression et un bouton Annuler pendant une tache en cours", async () => {
  mockPreview(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue({
    job_id: "job-1", release_name: "X", state: "staging", percent: 42,
    started_at: 1000, finished_at: null, error: null, result: null,
  });
  const user = userEvent.setup();
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });

  await waitFor(() => screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(screen.getByRole("button", { name: /Confirmer/i }));

  expect(await screen.findByText(/42\s*%/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Annuler/i })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Confirmer/i })).not.toBeInTheDocument();
});

it("Annuler appelle cancelCommitJob avec le job_id en cours", async () => {
  mockPreview(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue({
    job_id: "job-1", release_name: "X", state: "staging", percent: 10,
    started_at: 1000, finished_at: null, error: null, result: null,
  });
  vi.mocked(cancelCommitJob).mockResolvedValue({ status: "cancelling" });
  const user = userEvent.setup();
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });

  await waitFor(() => screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(await screen.findByRole("button", { name: /Annuler/i }));

  expect(cancelCommitJob).toHaveBeenCalledWith("job-1");
});

it("etat error : affiche le message et fait reapparaitre Confirmer", async () => {
  mockPreview(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue({
    job_id: "job-1", release_name: "X", state: "error", percent: 0,
    started_at: 1000, finished_at: 1001, error: "NAS déconnecté", result: null,
  });
  const user = userEvent.setup();
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });

  await waitFor(() => screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(screen.getByRole("button", { name: /Confirmer/i }));

  expect(await screen.findByText(/NAS déconnecté/)).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: /Confirmer/i })).toBeInTheDocument();
});

it("affiche le bouton Envoyer a C411 seulement apres confirmation, et affiche le lien du brouillon", async () => {
  const user = userEvent.setup();
  mockPreview(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue(DONE_JOB);
  vi.mocked(sendToTracker).mockResolvedValue({
    draft_id: 555, draft_url: "https://c411.org/user/drafts/555",
    duplicate_warning: null, presentation_warning: null, seed_warning: null,
  });

  renderPanel({
    localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn(),
    mediaType: "movie", radarrMovieId: 42, sonarrSeriesId: null, tmdbId: 603, tvdbId: null,
    genre: null, seasonNumber: null,
  });

  expect(screen.queryByRole("button", { name: /Créer un brouillon/i })).not.toBeInTheDocument();

  await waitFor(() => screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(screen.getByRole("button", { name: /Confirmer/i }));

  const sendButton = await screen.findByRole("button", { name: /Créer un brouillon/i });
  await user.click(sendButton);

  expect(await screen.findByText(/c411\.org\/user\/drafts\/555/)).toBeInTheDocument();
  expect(screen.getByText(/^Brouillon créé/)).toBeInTheDocument();
  expect(sendToTracker).toHaveBeenCalledWith(
    expect.objectContaining({
      releaseName: "Movie.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM",
      mediaType: "movie", radarrMovieId: 42, tmdbId: 603, direct: false,
    }),
  );
});

it("Uploader directement demande confirmation, appelle sendToTracker avec direct:true, affiche 'Uploade directement'", async () => {
  /* Retour d'un membre de l'equipe C411, 2026-09-07 : vrai endpoint
   * d'upload direct (POST /api/torrents), distinct des brouillons. */
  const user = userEvent.setup();
  mockPreview(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue(DONE_JOB);
  vi.mocked(verifyIntegrity).mockResolvedValue({ job_id: "integrity-1" });
  vi.mocked(integrityJobStatus).mockResolvedValue({
    job_id: "integrity-1", state: "done", percent: 100,
    started_at: 1, finished_at: 2, error: null,
    result: { passed: true, errors: [], warnings: [] },
  });
  vi.mocked(sendToTracker).mockResolvedValue({
    draft_id: 777, draft_url: "https://c411.org/torrents/abc123",
    duplicate_warning: null, presentation_warning: null, seed_warning: null,
  });
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

  renderPanel({
    localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn(),
    mediaType: "movie", radarrMovieId: 42, sonarrSeriesId: null, tmdbId: 603, tvdbId: null,
    genre: null, seasonNumber: null,
  });

  await waitFor(() => screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(await screen.findByRole("button", { name: /Uploader directement/i }));

  expect(confirmSpy).toHaveBeenCalled();
  expect(sendToTracker).toHaveBeenCalledWith(expect.objectContaining({ direct: true }));
  expect(await screen.findByText(/^Uploadé directement/)).toBeInTheDocument();
});

it("Uploader directement n'appelle rien si l'utilisateur annule la confirmation", async () => {
  const user = userEvent.setup();
  mockPreview(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue(DONE_JOB);
  vi.spyOn(window, "confirm").mockReturnValue(false);

  renderPanel({
    localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn(),
    mediaType: "movie", radarrMovieId: 42, sonarrSeriesId: null, tmdbId: 603, tvdbId: null,
    genre: null, seasonNumber: null,
  });

  await waitFor(() => screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(await screen.findByRole("button", { name: /Uploader directement/i }));

  expect(sendToTracker).not.toHaveBeenCalled();
});

it("Uploader directement lance d'abord une verification d'integrite avant sendToTracker", async () => {
  const user = userEvent.setup();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  mockPreview(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue(DONE_JOB);
  vi.mocked(verifyIntegrity).mockResolvedValue({ job_id: "integrity-1" });
  vi.mocked(integrityJobStatus).mockResolvedValue({
    job_id: "integrity-1", state: "done", percent: 100,
    started_at: 1, finished_at: 2, error: null,
    result: { passed: true, errors: [], warnings: [] },
  });
  vi.mocked(sendToTracker).mockResolvedValue({
    draft_id: 1, draft_url: "https://c411.org/torrents/1", duplicate_warning: null,
    presentation_warning: null, seed_warning: null,
  });

  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });
  await user.click(await screen.findByRole("button", { name: "Confirmer" }));
  await waitFor(() => screen.getByText(/BluRay\.AC3\.x264-TEAM$/));

  await user.click(screen.getByRole("button", { name: "Uploader directement" }));

  await waitFor(() => {
    expect(verifyIntegrity).toHaveBeenCalledWith(DONE_JOB.result.staged_path);
  });
  await waitFor(() => {
    expect(sendToTracker).toHaveBeenCalled();
  });
  expect(await screen.findByText(/Uploadé directement/)).toBeInTheDocument();
});

it("bloque l'upload direct si la verification d'integrite echoue, n'appelle jamais sendToTracker", async () => {
  const user = userEvent.setup();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  mockPreview(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue(DONE_JOB);
  vi.mocked(verifyIntegrity).mockResolvedValue({ job_id: "integrity-1" });
  vi.mocked(integrityJobStatus).mockResolvedValue({
    job_id: "integrity-1", state: "done", percent: 100,
    started_at: 1, finished_at: 2, error: null,
    result: { passed: false, errors: ["Fichier probablement tronqué."], warnings: [] },
  });

  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });
  await user.click(await screen.findByRole("button", { name: "Confirmer" }));
  await waitFor(() => screen.getByText(/BluRay\.AC3\.x264-TEAM$/));

  await user.click(screen.getByRole("button", { name: "Uploader directement" }));

  expect(await screen.findByText(/Fichier probablement tronqué/)).toBeInTheDocument();
  expect(sendToTracker).not.toHaveBeenCalled();
});

it("Creer un brouillon n'appelle jamais verifyIntegrity", async () => {
  const user = userEvent.setup();
  mockPreview(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue(DONE_JOB);
  vi.mocked(sendToTracker).mockResolvedValue({
    draft_id: "d1", draft_url: "https://c411.org/drafts/1", duplicate_warning: null,
    presentation_warning: null, seed_warning: null,
  });

  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });
  await user.click(await screen.findByRole("button", { name: "Confirmer" }));
  await waitFor(() => screen.getByText(/BluRay\.AC3\.x264-TEAM$/));

  await user.click(screen.getByRole("button", { name: "Créer un brouillon" }));

  await waitFor(() => expect(sendToTracker).toHaveBeenCalled());
  expect(verifyIntegrity).not.toHaveBeenCalled();
});

it("affiche l'avertissement d'ajout qBittorrent quand present (upload direct)", async () => {
  /* Retour utilisateur, 2026-09-07 : "le torrent n'est jamais envoye a
   * qbit !!!!" -- ajout auto a qBittorrent en mode direct, best-effort. */
  const user = userEvent.setup();
  mockPreview(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue(DONE_JOB);
  vi.mocked(verifyIntegrity).mockResolvedValue({ job_id: "integrity-1" });
  vi.mocked(integrityJobStatus).mockResolvedValue({
    job_id: "integrity-1", state: "done", percent: 100,
    started_at: 1, finished_at: 2, error: null,
    result: { passed: true, errors: [], warnings: [] },
  });
  vi.mocked(sendToTracker).mockResolvedValue({
    draft_id: 777, draft_url: "https://c411.org/torrents/abc123",
    duplicate_warning: null, presentation_warning: null,
    seed_warning: "Torrent envoyé à C411, mais pas ajouté à qBittorrent : non configuré (voir Réglages).",
  });
  vi.spyOn(window, "confirm").mockReturnValue(true);

  renderPanel({
    localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn(),
    mediaType: "movie", radarrMovieId: 42, sonarrSeriesId: null, tmdbId: 603, tvdbId: null,
    genre: null, seasonNumber: null,
  });

  await waitFor(() => screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(await screen.findByRole("button", { name: /Uploader directement/i }));

  expect(await screen.findByText(/pas ajouté à qBittorrent/i)).toBeInTheDocument();
});

it("affiche l'avertissement anti-doublon quand present", async () => {
  const user = userEvent.setup();
  mockPreview(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue(DONE_JOB);
  vi.mocked(sendToTracker).mockResolvedValue({
    draft_id: 555, draft_url: "https://c411.org/user/drafts/555",
    duplicate_warning: "1 release(s) déjà approuvée(s) pour cet identifiant TMDB...",
    presentation_warning: null, seed_warning: null,
  });

  renderPanel({
    localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn(),
    mediaType: "movie", radarrMovieId: 42, sonarrSeriesId: null, tmdbId: 603, tvdbId: null,
    genre: null, seasonNumber: null,
  });

  await waitFor(() => screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(await screen.findByRole("button", { name: /Créer un brouillon/i }));

  expect(await screen.findByText(/déjà approuvée/i)).toBeInTheDocument();
});

it("affiche l'avertissement de presentation incomplete (cle TMDB manquante) quand present", async () => {
  /* Retour C411, 2026-09-07 : tous les elements de la presentation sont
   * obligatoires -- sans cle TMDB, Pays/Createur(s)/Note/IMDB manqueront. */
  const user = userEvent.setup();
  mockPreview(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue(DONE_JOB);
  vi.mocked(sendToTracker).mockResolvedValue({
    draft_id: 555, draft_url: "https://c411.org/user/drafts/555",
    duplicate_warning: null,
    presentation_warning: "Description incomplète : clé API TMDB non configurée — Pays, créateur(s), note TMDB et lien IMDB seront absents (voir Réglages).", seed_warning: null,
  });

  renderPanel({
    localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn(),
    mediaType: "movie", radarrMovieId: 42, sonarrSeriesId: null, tmdbId: 603, tvdbId: null,
    genre: null, seasonNumber: null,
  });

  await waitFor(() => screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(screen.getByRole("button", { name: /Confirmer/i }));
  await user.click(await screen.findByRole("button", { name: /Créer un brouillon/i }));

  expect(await screen.findByText(/clé API TMDB non configurée/i)).toBeInTheDocument();
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
  mockPreview(ONE_GROUP);
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });
  await waitFor(() => screen.getByRole("button", { name: "Recalculer" }));

  const CORRECTED_GROUP: UploadGroupProposal[] = [
    { ...ONE_GROUP[0], release_name: "Un.Gars.Une.Fille.2020.MULTI.VFF.1080p.BluRay.AC3.x264-TEAM" },
  ];
  mockPreview(CORRECTED_GROUP);

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
    undefined,
  );
});

it("defaults to the globally active profile", async () => {
  mockPreview(ONE_GROUP);
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });

  await waitFor(() => {
    expect(prepareUploadPreview).toHaveBeenCalledWith(["/media/movie.mkv"], "c411", "Movie", undefined);
  });
});

it("lets the user override the profile for this one upload without changing the global active profile", async () => {
  const user = userEvent.setup();
  mockPreview(ONE_GROUP);
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });
  await waitFor(() => screen.getByRole("button", { name: "Recalculer" }));

  const select = screen.getByLabelText(/Profil pour cet upload/i);
  await user.selectOptions(select, "ygg");

  await waitFor(() => {
    expect(prepareUploadPreview).toHaveBeenLastCalledWith(["/media/movie.mkv"], "ygg", "Movie", undefined);
  });
});

it("transmet seasonPack a prepareUploadPreview quand fourni (bouton 'Preparer le pack', Bibliotheque)", async () => {
  mockPreview(ONE_GROUP);
  const seasonPack = {
    title: "Lucifer",
    team: "Frosties",
    is_full_series: true,
    seasons: [
      { season_number: 1, local_paths: ["/media/s01.mkv"] },
      { season_number: 2, local_paths: ["/media/s02.mkv"] },
    ],
  };
  renderPanel({
    localPaths: ["/media/s01.mkv", "/media/s02.mkv"],
    title: "Lucifer INTEGRALE",
    onClose: vi.fn(),
    seasonPack,
  });

  await waitFor(() => {
    expect(prepareUploadPreview).toHaveBeenCalledWith(
      ["/media/s01.mkv", "/media/s02.mkv"],
      "c411",
      "Lucifer INTEGRALE",
      seasonPack,
    );
  });
});

// --------------------------------------------------------------------------- //
// Modale (retour utilisateur, 2026-09-09 : "c'est etonnamant pas logique de
// tous mettre en bas de la page") -- toujours au meme endroit a l'ecran,
// quelle que soit la ligne cliquee ou le defilement de la page.
// --------------------------------------------------------------------------- //
it("s'affiche comme une fenetre modale (role dialog)", async () => {
  mockPreview(ONE_GROUP);
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });

  expect(await screen.findByRole("dialog")).toBeInTheDocument();
});

it("Fermer appelle onClose directement quand rien n'est confirme-mais-pas-envoye", async () => {
  const user = userEvent.setup();
  mockPreview(ONE_GROUP);
  const confirmSpy = vi.spyOn(window, "confirm");
  const onClose = vi.fn();
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose });

  await user.click(await screen.findByRole("button", { name: "Fermer" }));

  expect(onClose).toHaveBeenCalled();
  expect(confirmSpy).not.toHaveBeenCalled();
});

it("Echap appelle onClose directement quand rien n'est confirme-mais-pas-envoye", async () => {
  const user = userEvent.setup();
  mockPreview(ONE_GROUP);
  const onClose = vi.fn();
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose });
  await screen.findByRole("dialog");

  await user.keyboard("{Escape}");

  expect(onClose).toHaveBeenCalled();
});

it("le clic sur le fond assombri appelle onClose directement quand rien n'est confirme-mais-pas-envoye", async () => {
  const user = userEvent.setup();
  mockPreview(ONE_GROUP);
  const onClose = vi.fn();
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose });
  await screen.findByRole("dialog");

  // Le fond assombri est un ELEMENT DEDIE du tiroir (Drawer), plus le
  // parent direct de la boite de dialogue depuis la conversion overlay ->
  // tiroir (retour utilisateur, 2026-09-12) -- voir Drawer.tsx.
  await user.click(screen.getByTestId("drawer-backdrop"));

  expect(onClose).toHaveBeenCalled();
});

it("un clic A L'INTERIEUR de la boite de dialogue n'appelle jamais onClose", async () => {
  const user = userEvent.setup();
  mockPreview(ONE_GROUP);
  const onClose = vi.fn();
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose });
  const dialog = await screen.findByRole("dialog");

  await user.click(dialog);

  expect(onClose).not.toHaveBeenCalled();
});

it("Fermer demande confirmation quand un groupe est confirme mais pas encore envoye, respecte l'annulation", async () => {
  const user = userEvent.setup();
  mockPreview(ONE_GROUP);
  vi.mocked(prepareUploadCommit).mockResolvedValue({ job_id: "job-1" });
  vi.mocked(commitJobStatus).mockResolvedValue(DONE_JOB);
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
  const onClose = vi.fn();
  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose });

  await user.click(await screen.findByRole("button", { name: "Confirmer" }));
  await waitFor(() => screen.getByText(/BluRay\.AC3\.x264-TEAM$/));

  await user.click(screen.getByRole("button", { name: "Fermer" }));

  expect(confirmSpy).toHaveBeenCalled();
  expect(onClose).not.toHaveBeenCalled(); // annule -> le panneau reste ouvert

  confirmSpy.mockReturnValue(true);
  await user.click(screen.getByRole("button", { name: "Fermer" }));
  expect(onClose).toHaveBeenCalled();
});

it("affiche un message explicatif et la progression pendant l'analyse, jusqu'a resolution", async () => {
  /* Retour utilisateur (2026-09-09) : "juste Calcul de l'apercu [...] je
   * me suis fait avoir" -- le simple "Calcul de l'apercu…" muet devient un
   * message explicatif + une vraie progression (utile pour un pack), sans
   * bloquer le reste du formulaire. */
  vi.mocked(prepareUploadPreview).mockResolvedValue({ job_id: "preview-job-1" });
  let resolveStatus: (job: UploadPreviewJob) => void = () => {};
  vi.mocked(uploadPreviewJobStatus).mockImplementation(
    () => new Promise((resolve) => { resolveStatus = resolve; }),
  );

  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });

  await screen.findByText(/Analyse en cours/);
  expect(screen.getByText(/débit\/la fréquence d'image/)).toBeInTheDocument();

  resolveStatus({
    job_id: "preview-job-1", state: "done", processed: 1, total: 1,
    started_at: 0, finished_at: 1, error: null, result: ONE_GROUP,
  });

  await waitFor(() => {
    expect(screen.getByText(/Movie\.2020\.MULTI\.VFF\.1080p\.BluRay\.AC3\.x264-TEAM$/)).toBeInTheDocument();
  });
});

it("affiche la progression par fichier pour un pack multi-fichiers", async () => {
  vi.mocked(prepareUploadPreview).mockResolvedValue({ job_id: "preview-job-1" });
  vi.mocked(uploadPreviewJobStatus).mockResolvedValue({
    job_id: "preview-job-1", state: "analyzing", processed: 2, total: 5,
    started_at: 0, finished_at: null, error: null, result: null,
  });

  renderPanel({ localPaths: ["/media/a.mkv"], title: "Pack", onClose: vi.fn() });

  await screen.findByText(/Analyse en cours… \(2\/5 fichiers\)/);
});

it("le bouton Annuler pendant l'analyse appelle cancelUploadPreviewJob", async () => {
  const user = userEvent.setup();
  vi.mocked(prepareUploadPreview).mockResolvedValue({ job_id: "preview-job-1" });
  vi.mocked(uploadPreviewJobStatus).mockResolvedValue({
    job_id: "preview-job-1", state: "analyzing", processed: 0, total: 1,
    started_at: 0, finished_at: null, error: null, result: null,
  });
  vi.mocked(cancelUploadPreviewJob).mockResolvedValue({ status: "cancelling" });

  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });

  await user.click(await screen.findByRole("button", { name: "Annuler" }));

  expect(cancelUploadPreviewJob).toHaveBeenCalledWith("preview-job-1");
});

it("une analyse annulee affiche un message d'erreur explicite, permet de Recalculer", async () => {
  vi.mocked(prepareUploadPreview).mockResolvedValue({ job_id: "preview-job-1" });
  vi.mocked(uploadPreviewJobStatus).mockResolvedValue({
    job_id: "preview-job-1", state: "cancelled", processed: 0, total: 1,
    started_at: 0, finished_at: 1, error: null, result: null,
  });

  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });

  expect(await screen.findByText("Aperçu annulé.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Recalculer" })).toBeInTheDocument();
});

it("une analyse en erreur affiche le message d'erreur du job", async () => {
  vi.mocked(prepareUploadPreview).mockResolvedValue({ job_id: "preview-job-1" });
  vi.mocked(uploadPreviewJobStatus).mockResolvedValue({
    job_id: "preview-job-1", state: "error", processed: 0, total: 1,
    started_at: 0, finished_at: 1, error: "Chemin source non reconnu.", result: null,
  });

  renderPanel({ localPaths: ["/media/movie.mkv"], title: "Movie", onClose: vi.fn() });

  expect(await screen.findByText("Chemin source non reconnu.")).toBeInTheDocument();
});
