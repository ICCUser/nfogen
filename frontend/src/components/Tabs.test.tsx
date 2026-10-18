import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import Tabs from "./Tabs";

const ITEMS = [
  { value: "rules", label: "Règles" },
  { value: "templates", label: "Template" },
  { value: "preview", label: "Aperçu" },
] as const;

function Harness() {
  const [value, setValue] = useState<(typeof ITEMS)[number]["value"]>("rules");
  return (
    <>
      <Tabs label="Section" idPrefix="t" controls="panel" items={ITEMS} value={value} onChange={setValue} />
      <div id="panel" role="tabpanel" aria-labelledby={`t-${value}`}>
        panneau {value}
      </div>
    </>
  );
}

describe("Tabs", () => {
  it("expose une liste d'onglets nommee, l'onglet actif selectionne, relie au panneau", () => {
    render(<Harness />);
    expect(screen.getByRole("tablist", { name: "Section" })).toBeInTheDocument();
    const active = screen.getByRole("tab", { name: "Règles" });
    expect(active).toHaveAttribute("aria-selected", "true");
    expect(active).toHaveAttribute("aria-controls", "panel");
    expect(screen.getByRole("tab", { name: "Template" })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tabpanel", { name: "Règles" })).toHaveTextContent("panneau rules");
  });

  it("un seul arret Tab (l'onglet actif), fleches/Debut/Fin pour naviguer et activer", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.tab();
    expect(screen.getByRole("tab", { name: "Règles" })).toHaveFocus();

    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Template" })).toHaveFocus();
    expect(screen.getByRole("tab", { name: "Template" })).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{ArrowLeft}{ArrowLeft}");
    // En boucle : depuis le premier, gauche va au dernier.
    expect(screen.getByRole("tab", { name: "Aperçu" })).toHaveFocus();

    await user.keyboard("{Home}");
    expect(screen.getByRole("tab", { name: "Règles" })).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "Aperçu" })).toHaveAttribute("aria-selected", "true");
  });
});
