import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  listAllProfiles: vi.fn(),
  listManagedProfiles: vi.fn(),
}));

import { listAllProfiles, listManagedProfiles } from "../api/client";
import ProfilesListPage from "./ProfilesListPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <ProfilesListPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(listAllProfiles).mockReset();
  vi.mocked(listManagedProfiles).mockReset();
  vi.mocked(listManagedProfiles).mockResolvedValue([]);
});

describe("ProfilesListPage -- tableau triable (retour utilisateur, 2026-09-09)", () => {
  it("trie par defaut par nom de profil croissant (comportement d'origine)", async () => {
    vi.mocked(listAllProfiles).mockResolvedValue({ zeta: ["video"], alpha: ["video"] });
    renderPage();

    await screen.findByText("zeta");
    const names = screen.getAllByRole("row").slice(1).map((row) => row.textContent);
    expect(names[0]).toContain("alpha");
    expect(names[1]).toContain("zeta");
  });

  it("trie par nom au clic sur l'en-tête Profil, inverse au second clic", async () => {
    const user = userEvent.setup();
    vi.mocked(listAllProfiles).mockResolvedValue({ alpha: ["video"], zeta: ["video"] });
    renderPage();
    await screen.findByText("alpha");

    await user.click(screen.getByTestId("col-header-name"));

    await waitFor(() => {
      const names = screen.getAllByRole("row").slice(1).map((row) => row.textContent);
      expect(names[0]).toContain("zeta");
      expect(names[1]).toContain("alpha");
    });
  });
});
