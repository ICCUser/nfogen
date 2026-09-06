import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api/client", () => ({
  listAllProfiles: vi.fn(),
  readManagedProfile: vi.fn(),
  gapscanConfig: vi.fn(),
  gapscanStatus: vi.fn(),
  gapscanResults: vi.fn(),
}));

import { gapscanConfig, gapscanResults, gapscanStatus, listAllProfiles, readManagedProfile } from "./api/client";
import App from "./App";

beforeEach(() => {
  vi.mocked(listAllProfiles).mockResolvedValue({ c411: ["video"] });
  vi.mocked(readManagedProfile).mockResolvedValue({
    name: "c411", rules: { tracker: { display_name: "C411" } }, templates: {},
  });
  vi.mocked(gapscanConfig).mockResolvedValue({
    profile: "c411", tracker_configured: true, tracker_base_url: "https://c411.org",
    sonarr_configured: true, sonarr_url: "http://sonarr.local",
    radarr_configured: false, radarr_url: null,
    sonarr_path_mappings: {}, radarr_path_mappings: {},
    tracker_announce_url_configured: false, staging_dir: null,
  });
  vi.mocked(gapscanStatus).mockResolvedValue({
    state: "idle", total: 0, processed: 0, started_at: null, finished_at: null, error: null,
  });
  vi.mocked(gapscanResults).mockResolvedValue({ items: [], total: 0 });
});

describe("App", () => {
  it("renders one profile selector in the header, not per-page", async () => {
    render(
      <MemoryRouter initialEntries={["/gapscan"]}>
        <App />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("combobox", { name: /profil actif/i })).toBeInTheDocument();
  });

  it("shows the active profile's display_name in the nav label instead of a hard-coded name", async () => {
    render(
      <MemoryRouter initialEntries={["/gapscan"]}>
        <App />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("link", { name: /Scan C411/ })).toBeInTheDocument();
  });

  it("affiche un lien de navigation vers la bibliotheque (AUTOMATION.md, sous-projet 8)", async () => {
    render(
      <MemoryRouter initialEntries={["/gapscan"]}>
        <App />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("link", { name: /Bibliothèque/i })).toBeInTheDocument();
  });
});
