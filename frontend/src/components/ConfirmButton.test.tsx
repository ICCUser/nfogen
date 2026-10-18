import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ConfirmButton from "./ConfirmButton";

function renderButton(onConfirm = vi.fn()) {
  render(
    <ConfirmButton question="Supprimer ce profil ?" confirmLabel="Oui, supprimer" onConfirm={onConfirm}>
      Supprimer
    </ConfirmButton>,
  );
  return onConfirm;
}

describe("ConfirmButton", () => {
  it("le premier clic n'execute rien : il pose la question sur place, focus sur Annuler", async () => {
    const onConfirm = renderButton();
    await userEvent.click(screen.getByRole("button", { name: "Supprimer" }));

    expect(onConfirm).not.toHaveBeenCalled();
    const group = screen.getByRole("group", { name: "Supprimer ce profil ?" });
    expect(within(group).getByRole("button", { name: "Annuler" })).toHaveFocus();
  });

  it("execute l'action apres confirmation explicite", async () => {
    const onConfirm = renderButton();
    await userEvent.click(screen.getByRole("button", { name: "Supprimer" }));
    await userEvent.click(screen.getByRole("button", { name: "Oui, supprimer" }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });

  it("Annuler revient au bouton d'origine, focus compris, sans rien executer", async () => {
    const onConfirm = renderButton();
    await userEvent.click(screen.getByRole("button", { name: "Supprimer" }));
    await userEvent.click(screen.getByRole("button", { name: "Annuler" }));

    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Supprimer" })).toHaveFocus();
  });

  it("Echap annule sans remonter (ne ferme pas un tiroir englobant)", async () => {
    const onParentKeyDown = vi.fn();
    render(
      <div onKeyDown={onParentKeyDown}>
        <ConfirmButton question="Supprimer ?" confirmLabel="Oui, supprimer" onConfirm={vi.fn()}>
          Supprimer
        </ConfirmButton>
      </div>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Supprimer" }));
    fireEvent.keyDown(screen.getByRole("button", { name: "Annuler" }), { key: "Escape" });

    expect(onParentKeyDown).not.toHaveBeenCalled();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });
});
