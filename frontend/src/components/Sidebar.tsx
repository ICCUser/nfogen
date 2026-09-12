import { FileText, Home, Library, Send, Settings } from "lucide-react";
import { NavLink } from "react-router-dom";

/** Rail lateral fixe (icone + libelle), inspire de la suite *arr
 * (Radarr/Sonarr) -- remplace la nav du haut precedente (App.tsx).
 * Se replie en barre du bas sous 768px (voir classes md: ci-dessous),
 * voir docs/superpowers/specs/2026-09-12-frontend-shell-redesign-design.md. */

const LINKS = [
  { to: "/", label: "Générer", icon: Home, end: true },
  { to: "/library", label: "Bibliothèque", icon: Library, end: false },
  { to: "/seed-queue", label: "À mettre en seed", icon: Send, end: false },
  { to: "/profils", label: "Profils", icon: FileText, end: false },
  { to: "/settings", label: "Réglages", icon: Settings, end: false },
] as const;

function linkClass({ isActive }: { isActive: boolean }) {
  return `flex items-center gap-3 px-4 py-2.5 text-sm transition-colors md:flex-col md:gap-1 md:px-2 md:py-1.5 md:text-xs ${
    isActive
      ? "border-l-2 border-accent bg-surface-2 font-medium text-ink md:border-l-0 md:border-t-2"
      : "text-ink-dim hover:bg-surface-2 hover:text-ink"
  }`;
}

export default function Sidebar() {
  return (
    <nav
      aria-label="Navigation principale"
      className="flex shrink-0 flex-col border-r border-line bg-surface md:fixed md:inset-x-0 md:bottom-0 md:top-auto md:h-auto md:w-full md:flex-row md:justify-around md:border-r-0 md:border-t"
    >
      <div className="px-4 py-4 font-display text-lg font-bold text-ink md:hidden">
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
