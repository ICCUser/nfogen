import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "./SettingsPage";

vi.mock("../api/client", () => ({
  createAccount: vi.fn(),
  deleteAccount: vi.fn(),
  listAccounts: vi.fn(),
}));
vi.mock("../api/settings", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/settings")>();
  return { ...actual, getAuthStatus: vi.fn(), login: vi.fn(), logout: vi.fn() };
});

import { getAuthStatus, login } from "../api/settings";

const UNAUTHENTICATED_TOKEN_ONLY = {
  authRequired: true,
  authenticated: false,
  tokenLoginEnabled: true,
  accountsLoginEnabled: false,
  accountsBootstrapAvailable: false,
};

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => vi.resetAllMocks());

describe("SettingsPage - connexion par token", () => {
  it("chemin heureux : token valide -> login() appele, statut 'Connecte' affiche", async () => {
    vi.mocked(getAuthStatus)
      .mockResolvedValueOnce(UNAUTHENTICATED_TOKEN_ONLY)
      .mockResolvedValueOnce({ ...UNAUTHENTICATED_TOKEN_ONLY, authenticated: true });
    vi.mocked(login).mockResolvedValue(undefined);

    render(<SettingsPage />);

    const tokenInput = await screen.findByLabelText("Token API");
    await userEvent.type(tokenInput, "mon-token-secret");
    await userEvent.click(screen.getByRole("button", { name: "Se connecter" }));

    expect(login).toHaveBeenCalledWith({ token: "mon-token-secret" });
    expect(await screen.findByText("Connecté.")).toBeInTheDocument();
  });

  it("token invalide : message d'erreur affiche, formulaire de connexion toujours visible", async () => {
    vi.mocked(getAuthStatus).mockResolvedValue(UNAUTHENTICATED_TOKEN_ONLY);
    vi.mocked(login).mockRejectedValue(new Error("Token API invalide."));

    render(<SettingsPage />);

    const tokenInput = await screen.findByLabelText("Token API");
    await userEvent.type(tokenInput, "mauvais-token");
    await userEvent.click(screen.getByRole("button", { name: "Se connecter" }));

    expect(await screen.findByText("Token API invalide.")).toBeInTheDocument();
    expect(screen.queryByText("Connecté.")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Token API")).toBeInTheDocument();
  });
});
