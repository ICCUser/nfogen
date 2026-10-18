import { type Header, flexRender } from "@tanstack/react-table";
import { ChevronDown, ChevronUp, ChevronsUpDown } from "lucide-react";

/** En-tete de colonne commun aux tableaux TanStack (audit front
 * 2026-10-14, lot 5). Avant : `<th onClick>` -- inaccessible au clavier,
 * aucun `aria-sort`, indicateur " ▲"/" ▼" en texte colle au libelle.
 * Desormais : un vrai bouton dans le `<th>` (Tab + Entree/Espace),
 * `aria-sort` lu par les lecteurs d'ecran, chevrons Lucide -- et un double
 * chevron estompe sur les colonnes triables non triees, pour signaler
 * qu'elles le sont. `data-testid` reste `col-header-<id>`, sur l'element
 * cliquable. */
export default function SortableHeader<T>({ header, className }: { header: Header<T, unknown>; className?: string }) {
  const id = header.column.id;
  const label = header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext());

  if (!header.column.getCanSort()) {
    return (
      <th data-testid={`col-header-${id}`} className={className}>
        {label}
      </th>
    );
  }

  const sorted = header.column.getIsSorted();
  const Icon = sorted === "asc" ? ChevronUp : sorted === "desc" ? ChevronDown : ChevronsUpDown;
  return (
    <th
      aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}
      className={className}
    >
      <button
        type="button"
        data-testid={`col-header-${id}`}
        onClick={header.column.getToggleSortingHandler()}
        className="-mx-1 inline-flex items-center gap-1 rounded-sm px-1 text-left [text-transform:inherit] transition-[color,opacity] duration-100 hover:text-ink active:opacity-60"
      >
        {label}
        <Icon size={12} aria-hidden="true" className={sorted ? "text-ink" : "opacity-40"} />
      </button>
    </th>
  );
}
