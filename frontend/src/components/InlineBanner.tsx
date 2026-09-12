import type { ReactNode } from "react";

/** Bandeau fin ancre AU-DESSUS du contenu concerne (jamais au milieu --
 * retour utilisateur, 2026-09-12, "les pack disponible en plein milieu
 * qui casse le visuel"). Une ligne par element fourni par l'appelant. */
export default function InlineBanner({ children }: { children: ReactNode }) {
  return <div className="mb-3 divide-y divide-line rounded-md border border-line bg-surface-2">{children}</div>;
}
