import type { ReactNode } from "react";

/** Barre d'outils commune a toutes les pages : titre + sous-titre optionnel
 * a gauche, controles (recherche/filtres/actions) a droite -- jamais
 * d'element flottant au milieu du contenu (retour utilisateur, 2026-09-12).
 * Sous le breakpoint `sm`, les controles passent en dessous, pleine
 * largeur, plutot que de se compresser horizontalement. */
export default function PageToolbar({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
      <div>
        <h1 className="font-display text-xl font-semibold text-ink">{title}</h1>
        {subtitle && <p className="text-xs text-ink-dim">{subtitle}</p>}
      </div>
      {children && <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">{children}</div>}
    </div>
  );
}
