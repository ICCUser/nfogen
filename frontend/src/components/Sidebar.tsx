import { FileText, Home, Library, Send, Settings } from "lucide-react";
import { NavLink } from "react-router-dom";

/** Rail lateral fixe (icone + libelle) sur desktop, inspire de la suite
 * *arr (Radarr/Sonarr) -- remplace la nav du haut precedente (App.tsx).
 * Mobile-first : les classes de base sont la barre du bas (< 768px), le
 * prefixe `md:` (768px et au-dessus, convention Tailwind) bascule vers le
 * rail lateral. Voir docs/superpowers/specs/
 * 2026-09-12-frontend-shell-redesign-design.md. */

const LINKS = [
  { to: "/", label: "Générer", icon: Home, end: true },
  { to: "/library", label: "Bibliothèque", icon: Library, end: false },
  { to: "/seed-queue", label: "À mettre en seed", icon: Send, end: false },
  { to: "/profils", label: "Profils", icon: FileText, end: false },
  { to: "/settings", label: "Réglages", icon: Settings, end: false },
] as const;

function linkClass({ isActive }: { isActive: boolean }) {
  return `flex flex-col items-center gap-1 px-2 py-1.5 text-xs transition-colors md:flex-row md:gap-3 md:px-4 md:py-2.5 md:text-sm ${
    isActive
      ? "border-t-2 border-accent bg-surface-2 font-medium text-ink md:border-t-0 md:border-l-2"
      : "text-ink-dim hover:bg-surface-2 hover:text-ink"
  }`;
}

export default function Sidebar() {
  return (
    <nav
      aria-label="Navigation principale"
      className="fixed inset-x-0 bottom-0 z-40 flex justify-around border-t border-line bg-surface md:static md:inset-auto md:h-auto md:w-auto md:shrink-0 md:flex-col md:justify-start md:border-r md:border-t-0"
    >
      <div className="hidden px-4 py-4 font-display text-lg font-bold text-ink md:block">
        nfogen<span className="font-mono text-sm text-accent">.nfo</span>
      </div>
      {LINKS.map(({ to, label, icon: Icon, end }) => (
        <NavLink key={to} to={to} end={end} className={linkClass}>
          <Icon size={18} aria-hidden="true" />
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
