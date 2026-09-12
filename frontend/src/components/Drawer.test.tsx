import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import Drawer from "./Drawer";

describe("Drawer", () => {
  it("affiche son contenu et un bouton de fermeture", async () => {
    const onClose = vi.fn();
    render(
      <Drawer onClose={onClose}>
        <p>Contenu du tiroir</p>
      </Drawer>,
    );
    expect(screen.getByText("Contenu du tiroir")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /fermer/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("appelle onClose au clic sur le fond assombri", async () => {
    const onClose = vi.fn();
    render(
      <Drawer onClose={onClose}>
        <p>Contenu</p>
      </Drawer>,
    );
    await userEvent.click(screen.getByTestId("drawer-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
