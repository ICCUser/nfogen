import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import Sidebar from "./Sidebar";

describe("Sidebar", () => {
  it("affiche un lien vers chacune des 5 pages", () => {
    render(
      <MemoryRouter initialEntries={["/library"]}>
        <Sidebar />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: /Générer/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Bibliothèque/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /À mettre en seed/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Profils/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Réglages/i })).toBeInTheDocument();
  });

  it("marque le lien de la page active avec aria-current", () => {
    render(
      <MemoryRouter initialEntries={["/library"]}>
        <Sidebar />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: /Bibliothèque/i })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: /Générer/i })).not.toHaveAttribute("aria-current");
  });
});
