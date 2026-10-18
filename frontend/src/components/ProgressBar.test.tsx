import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ProgressBar from "./ProgressBar";

describe("ProgressBar", () => {
  it("expose sa valeur (arrondie, bornee) et remplit par scale, pas par width", () => {
    render(<ProgressBar value={42.6} label="Scan" />);
    const bar = screen.getByRole("progressbar", { name: "Scan" });
    expect(bar).toHaveAttribute("aria-valuenow", "43");
    const fill = bar.firstElementChild as HTMLElement;
    expect(fill.style.scale).toBe("0.426 1");
    expect(fill.style.width).toBe("");
  });

  it("borne les valeurs hors de 0-100", () => {
    render(<ProgressBar value={140} label="Trop" />);
    expect(screen.getByRole("progressbar", { name: "Trop" })).toHaveAttribute("aria-valuenow", "100");
  });

  it("cale la duree de transition sur l'intervalle de polling", () => {
    render(<ProgressBar value={10} label="Scan" pollMs={1000} />);
    const fill = screen.getByRole("progressbar").firstElementChild as HTMLElement;
    expect(fill.style.transitionDuration).toBe("900ms");
  });

  it("value=null : indeterminee, sans aria-valuenow, segment anime (sauf mouvement reduit)", () => {
    render(<ProgressBar value={null} label="Récupération" />);
    const bar = screen.getByRole("progressbar", { name: "Récupération" });
    expect(bar).not.toHaveAttribute("aria-valuenow");
    const segment = bar.firstElementChild as HTMLElement;
    expect(segment.className).toContain("animate-progress-indeterminate");
    expect(segment.className).toContain("motion-reduce:animate-none");
  });
});
