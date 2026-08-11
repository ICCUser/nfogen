import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import ErrorBoundary from "./ErrorBoundary";

function Boom(): never {
  throw new Error("categories.join is not a function");
}

describe("ErrorBoundary", () => {
  it("renders children normally when nothing throws", () => {
    render(
      <ErrorBoundary>
        <p>Contenu normal</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("Contenu normal")).toBeInTheDocument();
  });

  it("catches a render error instead of leaving a blank page", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );

    expect(screen.getByText("Une erreur inattendue est survenue.")).toBeInTheDocument();
    expect(screen.getByText("categories.join is not a function")).toBeInTheDocument();

    consoleError.mockRestore();
  });

  it("'Reessayer' clears the error state so children can render again", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    let shouldThrow = true;
    function MaybeBoom() {
      if (shouldThrow) throw new Error("boom");
      return <p>Retablie</p>;
    }

    render(
      <ErrorBoundary>
        <MaybeBoom />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Une erreur inattendue est survenue.")).toBeInTheDocument();

    shouldThrow = false;
    await userEvent.click(screen.getByRole("button", { name: "Reessayer" }));

    expect(screen.getByText("Retablie")).toBeInTheDocument();
    consoleError.mockRestore();
  });
});
