import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import InlineBanner from "./InlineBanner";

describe("InlineBanner", () => {
  it("affiche les enfants fournis", () => {
    render(
      <InlineBanner>
        <p>Braquo — INTEGRALE disponible</p>
      </InlineBanner>,
    );
    expect(screen.getByText("Braquo — INTEGRALE disponible")).toBeInTheDocument();
  });
});
