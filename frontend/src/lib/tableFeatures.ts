import {
  createSortedRowModel,
  rowSortingFeature,
  sortFn_alphanumeric,
  sortFn_basic,
  sortFn_text,
  tableFeatures,
} from "@tanstack/react-table";

/** Fonctionnalites TanStack Table v9 communes aux 3 tableaux de l'appli
 * (Bibliotheque, Profils, file de seed) -- en v9 chaque table declare
 * explicitement ce qu'elle utilise (migration v8 -> v9, 2026-11-07).
 *
 * - Tri seulement (aucun filtre/pagination cote table).
 * - `sortedRowModel` : tri cote navigateur (Profils, file de seed). La
 *   Bibliotheque trie cote serveur (`manualSorting: true`) : la v9 ignore
 *   alors ce modele et garde l'ordre recu -- une seule definition suffit.
 * - Comparateurs du tri automatique de la v8 (texte/alphanumerique pour les
 *   chaines, basique pour les nombres) : en v9, seuls ceux enregistres
 *   ici sont resolus par `sortFn: "auto"`. */
export const sortingTableFeatures = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: { alphanumeric: sortFn_alphanumeric, text: sortFn_text, basic: sortFn_basic },
});

export type SortingTableFeatures = typeof sortingTableFeatures;
