import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import AliasesField from "./AliasesField";

// fireEvent.change (pas userEvent.type) : le contenu contient des accolades,
// que la syntaxe clavier de userEvent interprete comme des touches speciales.

describe("AliasesField", () => {
  it("initializes the textarea from the given value", () => {
    render(<AliasesField value={{ x264: ["avc"] }} onChange={vi.fn()} />);
    expect(screen.getByRole("textbox")).toHaveValue('{"x264":["avc"]}');
  });

  it("parses valid JSON and reports it via onChange", () => {
    const onChange = vi.fn();
    render(<AliasesField value={undefined} onChange={onChange} />);

    fireEvent.change(screen.getByRole("textbox"), { target: { value: '{"x265":["hevc"]}' } });

    expect(onChange).toHaveBeenLastCalledWith({ x265: ["hevc"] });
  });

  it("reports undefined for an empty field (not an empty object)", async () => {
    const onChange = vi.fn();
    render(<AliasesField value={{ x264: ["avc"] }} onChange={onChange} />);

    await userEvent.clear(screen.getByRole("textbox"));

    expect(onChange).toHaveBeenLastCalledWith(undefined);
  });

  it("shows an error message and does not call onChange on invalid JSON", () => {
    const onChange = vi.fn();
    render(<AliasesField value={undefined} onChange={onChange} />);

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "{not json" } });

    expect(screen.getByText("JSON invalide")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });
});
