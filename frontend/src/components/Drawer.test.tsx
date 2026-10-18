import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import Drawer from "./Drawer";

describe("Drawer", () => {
  it("affiche son contenu et un bouton de fermeture", async () => {
    const onClose = vi.fn();
    render(
      <Drawer onClose={onClose} label="Tiroir de test">
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
      <Drawer onClose={onClose} label="Tiroir de test">
        <p>Contenu</p>
      </Drawer>,
    );
    await userEvent.click(screen.getByTestId("drawer-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("est un dialog modal nomme, qui recoit le focus a l'ouverture", () => {
    render(
      <Drawer onClose={vi.fn()} label="Préparer l'upload — Film">
        <p>Contenu</p>
      </Drawer>,
    );
    const dialog = screen.getByRole("dialog", { name: "Préparer l'upload — Film" });
    expect(dialog).toHaveAttribute("open");
    expect(screen.getByTestId("drawer-panel")).toHaveFocus();
  });

  it("Echap demande la fermeture via onClose (meme garde-fou que X et le fond)", async () => {
    const onClose = vi.fn();
    render(
      <Drawer onClose={onClose} label="Tiroir de test">
        <p>Contenu</p>
      </Drawer>,
    );
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("open=false ferme le dialog, rend le focus au declencheur puis appelle onExited", async () => {
    const onExited = vi.fn();
    function Harness({ open }: { open: boolean }) {
      return (
        <>
          <button type="button">Ouvrir</button>
          <Drawer open={open} onClose={vi.fn()} onExited={onExited} label="Tiroir de test">
            <p>Contenu</p>
          </Drawer>
        </>
      );
    }
    // Le declencheur a le focus avant l'ouverture, comme apres un clic reel.
    const { rerender } = render(<Harness open={false} />);
    const trigger = screen.getByRole("button", { name: "Ouvrir" });
    trigger.focus();
    rerender(<Harness open />);
    expect(screen.getByTestId("drawer-panel")).toHaveFocus();

    rerender(<Harness open={false} />);
    // Pas de transitionend sous jsdom : c'est le filet temporise qui conclut.
    await waitFor(() => expect(onExited).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
