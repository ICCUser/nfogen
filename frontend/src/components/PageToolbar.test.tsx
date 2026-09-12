import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import PageToolbar from "./PageToolbar";

describe("PageToolbar", () => {
  it("affiche le titre, le sous-titre optionnel et les enfants", () => {
    render(
      <PageToolbar title="Bibliothèque" subtitle="Dernière synchro : il y a 1 min">
        <button>Rafraîchir</button>
      </PageToolbar>,
    );
    expect(screen.getByRole("heading", { name: "Bibliothèque" })).toBeInTheDocument();
    expect(screen.getByText("Dernière synchro : il y a 1 min")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rafraîchir" })).toBeInTheDocument();
  });

  it("fonctionne sans sous-titre", () => {
    render(<PageToolbar title="Réglages" />);
    expect(screen.getByRole("heading", { name: "Réglages" })).toBeInTheDocument();
  });
});
