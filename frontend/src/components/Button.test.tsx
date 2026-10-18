import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import Button from "./Button";
import { buttonClass } from "./buttonClass";

describe("Button", () => {
  it("est de type button par defaut (ne soumet jamais un formulaire englobant)", () => {
    render(<Button>Tester</Button>);
    expect(screen.getByRole("button", { name: "Tester" })).toHaveAttribute("type", "button");
  });

  it("transmet onClick et ajoute la classe supplementaire", async () => {
    const onClick = vi.fn();
    render(
      <Button variant="link-danger" className="text-xs" onClick={onClick}>
        Annuler
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Annuler" });
    expect(button.className).toContain("text-crit");
    expect(button.className).toContain("text-xs");
    await userEvent.click(button);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("ne declenche rien une fois desactive", async () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Enregistrer
      </Button>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("buttonClass", () => {
  it("donne un retour a l'appui aux boutons pleins, sans taille pour les liens", () => {
    expect(buttonClass("primary", "sm")).toContain("not-disabled:active:");
    expect(buttonClass("primary", "sm")).toContain("px-3 py-1.5 text-xs");
    expect(buttonClass("link")).not.toContain("px-");
  });
});
