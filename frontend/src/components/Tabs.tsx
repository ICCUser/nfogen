import { type KeyboardEvent, useRef } from "react";

/** Liste d'onglets accessible (audit front 2026-10-14, lot 5) -- avant,
 * deux rangees de simples boutons (ProfileEditorPage), sans role ni etat
 * selectionne, et deux styles sans lien pour deux niveaux d'une meme
 * hierarchie.
 *
 * - `role="tablist"`/`"tab"`, `aria-selected`, `aria-controls` vers le
 *   panneau commande.
 * - Clavier (motif ARIA "tabs") : un seul arret Tab sur l'onglet actif,
 *   fleches gauche/droite (en boucle), Debut/Fin pour se deplacer et
 *   activer.
 * - `variant` distingue la hierarchie : "underline" (niveau 1, ex. la
 *   categorie) vs "segmented" (niveau 2, controle segmente). */
export default function Tabs<T extends string>({
  items,
  value,
  onChange,
  label,
  controls,
  idPrefix,
  variant = "underline",
  mono = false,
}: {
  items: readonly { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  /** Nom accessible de la liste d'onglets. */
  label: string;
  /** id du panneau que ces onglets commandent. */
  controls: string;
  /** Prefixe des id d'onglets (`${idPrefix}-${value}`), pour aria-labelledby. */
  idPrefix: string;
  variant?: "underline" | "segmented";
  /** Libelles litteraux (ex. noms de categorie) : police monospace. */
  mono?: boolean;
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  function move(to: number) {
    const next = items[(to + items.length) % items.length];
    onChange(next.value);
    refs.current[next.value]?.focus();
  }

  function onKeyDown(e: KeyboardEvent, index: number) {
    const keys: Record<string, number> = {
      ArrowRight: index + 1,
      ArrowLeft: index - 1,
      Home: 0,
      End: items.length - 1,
    };
    if (e.key in keys) {
      e.preventDefault();
      move(keys[e.key]);
    }
  }

  const listClass =
    variant === "underline"
      ? "flex gap-1 overflow-x-auto border-b border-line"
      : "inline-flex gap-0.5 rounded-md bg-surface-2 p-0.5";

  return (
    <div role="tablist" aria-label={label} className={listClass}>
      {items.map((item, index) => {
        const selected = item.value === value;
        const tabClass =
          variant === "underline"
            ? `-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors duration-100 active:opacity-60 ${
                selected ? "border-accent text-ink" : "border-transparent text-ink-faint hover:text-ink-dim"
              }`
            : `rounded px-3 py-1 text-sm transition-[color,background-color] duration-100 active:opacity-70 ${
                selected ? "bg-surface font-medium text-ink shadow-sm" : "text-ink-dim hover:text-ink"
              }`;
        return (
          <button
            key={item.value}
            ref={(el) => {
              refs.current[item.value] = el;
            }}
            type="button"
            role="tab"
            id={`${idPrefix}-${item.value}`}
            aria-selected={selected}
            aria-controls={controls}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(item.value)}
            onKeyDown={(e) => onKeyDown(e, index)}
            className={`${tabClass} ${mono ? "font-mono" : ""}`}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
