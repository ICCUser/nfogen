import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import ActiveTransfersTray from "./ActiveTransfersTray";

vi.mock("../api/client", () => ({
  listCommitJobs: vi.fn(),
  cancelCommitJob: vi.fn(),
}));

import { cancelCommitJob, listCommitJobs } from "../api/client";

beforeEach(() => {
  vi.mocked(listCommitJobs).mockReset();
  vi.mocked(cancelCommitJob).mockReset();
});

afterEach(() => vi.restoreAllMocks());

const ACTIVE_JOB = {
  job_id: "job-1", release_name: "Movie.2020.BluRay-TEAM", state: "staging" as const, percent: 30,
  started_at: 1000, finished_at: null, error: null, result: null,
};

const DONE_JOB = {
  job_id: "job-2", release_name: "Show.S01.WEB-TEAM", state: "done" as const, percent: 100,
  started_at: 900, finished_at: 950, error: null,
  result: { release_name: "Show.S01.WEB-TEAM", staged_path: "p", torrent_path: "t", nfo_path: "n" },
};

it("n'affiche rien quand aucune tache active", async () => {
  vi.mocked(listCommitJobs).mockResolvedValue([]);
  const { container } = render(<ActiveTransfersTray />);

  await waitFor(() => expect(listCommitJobs).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});

it("affiche les taches actives avec leur pourcentage, masque les taches terminees", async () => {
  vi.mocked(listCommitJobs).mockResolvedValue([ACTIVE_JOB, DONE_JOB]);
  render(<ActiveTransfersTray />);

  expect(await screen.findByText(/Movie\.2020\.BluRay-TEAM/)).toBeInTheDocument();
  expect(screen.queryByText(/Show\.S01\.WEB-TEAM/)).not.toBeInTheDocument();
  expect(screen.getByText(/30\s*%/)).toBeInTheDocument();
});

it("Annuler appelle cancelCommitJob avec le bon job_id", async () => {
  vi.mocked(listCommitJobs).mockResolvedValue([ACTIVE_JOB]);
  vi.mocked(cancelCommitJob).mockResolvedValue({ status: "cancelling" });
  const user = userEvent.setup();
  render(<ActiveTransfersTray />);

  await user.click(await screen.findByRole("button", { name: /Annuler/i }));

  expect(cancelCommitJob).toHaveBeenCalledWith("job-1");
});
