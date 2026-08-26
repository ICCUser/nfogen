import type { ReactNode } from "react";

interface ListEditorProps<T> {
  items: T[];
  onChange: (items: T[]) => void;
  newItem: () => T;
  renderRow: (item: T, update: (patch: Partial<T>) => void) => ReactNode;
  addLabel: string;
}

/** Editeur generique d'une liste d'objets (tokens, cross_checks,
 * track_language_checks...) : ajout/suppression de lignes, rendu de chaque
 * ligne delegue a l'appelant. */
export function ListEditor<T>({ items, onChange, newItem, renderRow, addLabel }: ListEditorProps<T>) {
  function updateAt(i: number, patch: Partial<T>) {
    const next = items.slice();
    next[i] = { ...next[i], ...patch };
    onChange(next);
  }
  function removeAt(i: number) {
    onChange(items.filter((_, idx) => idx !== i));
  }
  function add() {
    onChange([...items, newItem()]);
  }

  return (
    <div className="space-y-2">
      {items.map((item, i) => (
        <div key={i} className="flex items-start gap-2 rounded-md border border-line p-2">
          <div className="flex-1 space-y-1">{renderRow(item, (patch) => updateAt(i, patch))}</div>
          <button
            type="button"
            onClick={() => removeAt(i)}
            className="shrink-0 text-xs text-crit hover:underline"
          >
            Supprimer
          </button>
        </div>
      ))}
      <button type="button" onClick={add} className="text-sm text-accent-ink underline">
        + {addLabel}
      </button>
    </div>
  );
}

interface KeyValueEditorProps {
  value: Record<string, string>;
  onChange: (value: Record<string, string>) => void;
  keyPlaceholder: string;
  valuePlaceholder: string;
}

/** Editeur d'un dictionnaire string -> string (ex. require_one_of_groups). */
export function KeyValueEditor({ value, onChange, keyPlaceholder, valuePlaceholder }: KeyValueEditorProps) {
  const entries = Object.entries(value);

  function setEntries(next: [string, string][]) {
    onChange(Object.fromEntries(next));
  }

  return (
    <div className="space-y-2">
      {entries.map(([k, v], i) => (
        <div key={i} className="flex gap-2">
          <input
            className="w-1/3 rounded border border-line-strong bg-surface px-2 py-1 text-sm text-ink"
            placeholder={keyPlaceholder}
            value={k}
            onChange={(e) => {
              const next = entries.slice();
              next[i] = [e.target.value, v];
              setEntries(next);
            }}
          />
          <input
            className="flex-1 rounded border border-line-strong bg-surface px-2 py-1 text-sm text-ink"
            placeholder={valuePlaceholder}
            value={v}
            onChange={(e) => {
              const next = entries.slice();
              next[i] = [k, e.target.value];
              setEntries(next);
            }}
          />
          <button
            type="button"
            className="text-xs text-crit hover:underline"
            onClick={() => setEntries(entries.filter((_, idx) => idx !== i))}
          >
            Supprimer
          </button>
        </div>
      ))}
      <button
        type="button"
        className="text-sm text-accent-ink underline"
        onClick={() => setEntries([...entries, ["", ""]])}
      >
        + Ajouter
      </button>
    </div>
  );
}
