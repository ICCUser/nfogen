import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { KeyValueEditor, ListEditor } from "./ListEditor";

interface Token {
  name: string;
}

describe("ListEditor", () => {
  it("renders one row per item and delegates rendering to renderRow", () => {
    render(
      <ListEditor<Token>
        items={[{ name: "a" }, { name: "b" }]}
        onChange={vi.fn()}
        newItem={() => ({ name: "" })}
        renderRow={(item) => <span>{item.name}</span>}
        addLabel="Ajouter un token"
      />,
    );

    expect(screen.getByText("a")).toBeInTheDocument();
    expect(screen.getByText("b")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Supprimer" })).toHaveLength(2);
  });

  it("appends a new item on 'add'", async () => {
    const onChange = vi.fn();
    render(
      <ListEditor<Token>
        items={[{ name: "a" }]}
        onChange={onChange}
        newItem={() => ({ name: "nouveau" })}
        renderRow={(item) => <span>{item.name}</span>}
        addLabel="Ajouter un token"
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "+ Ajouter un token" }));

    expect(onChange).toHaveBeenCalledWith([{ name: "a" }, { name: "nouveau" }]);
  });

  it("removes only the targeted row", async () => {
    const onChange = vi.fn();
    render(
      <ListEditor<Token>
        items={[{ name: "a" }, { name: "b" }, { name: "c" }]}
        onChange={onChange}
        newItem={() => ({ name: "" })}
        renderRow={(item) => <span>{item.name}</span>}
        addLabel="Ajouter"
      />,
    );

    await userEvent.click(screen.getAllByRole("button", { name: "Supprimer" })[1]);

    expect(onChange).toHaveBeenCalledWith([{ name: "a" }, { name: "c" }]);
  });

  it("merges a partial patch into the targeted item without touching the others", () => {
    const onChange = vi.fn();
    let update!: (patch: Partial<Token>) => void;
    render(
      <ListEditor<Token>
        items={[{ name: "a" }, { name: "b" }]}
        onChange={onChange}
        newItem={() => ({ name: "" })}
        renderRow={(item, updateFn) => {
          if (item.name === "b") update = updateFn;
          return <span>{item.name}</span>;
        }}
        addLabel="Ajouter"
      />,
    );

    update({ name: "b-modifie" });

    expect(onChange).toHaveBeenCalledWith([{ name: "a" }, { name: "b-modifie" }]);
  });
});

describe("KeyValueEditor", () => {
  it("renders one input pair per entry", () => {
    render(
      <KeyValueEditor
        value={{ identifier: "message A" }}
        onChange={vi.fn()}
        keyPlaceholder="groupe"
        valuePlaceholder="message"
      />,
    );

    expect(screen.getByPlaceholderText("groupe")).toHaveValue("identifier");
    expect(screen.getByPlaceholderText("message")).toHaveValue("message A");
  });

  it("adds an empty entry on 'add'", async () => {
    const onChange = vi.fn();
    render(
      <KeyValueEditor value={{}} onChange={onChange} keyPlaceholder="groupe" valuePlaceholder="message" />,
    );

    await userEvent.click(screen.getByRole("button", { name: "+ Ajouter" }));

    expect(onChange).toHaveBeenCalledWith({ "": "" });
  });

  it("removes an entry by key", async () => {
    const onChange = vi.fn();
    render(
      <KeyValueEditor
        value={{ a: "1", b: "2" }}
        onChange={onChange}
        keyPlaceholder="k"
        valuePlaceholder="v"
      />,
    );

    await userEvent.click(screen.getAllByRole("button", { name: "Supprimer" })[0]);

    expect(onChange).toHaveBeenCalledWith({ b: "2" });
  });

  it("edits a value in place", async () => {
    const onChange = vi.fn();
    render(
      <KeyValueEditor value={{ a: "1" }} onChange={onChange} keyPlaceholder="k" valuePlaceholder="v" />,
    );

    await userEvent.type(screen.getByPlaceholderText("v"), "!");

    expect(onChange).toHaveBeenLastCalledWith({ a: "1!" });
  });
});
