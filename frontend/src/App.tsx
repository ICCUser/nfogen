import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import GapScanPage from "./pages/GapScanPage";
import GeneratePage from "./pages/GeneratePage";
import ProfilesListPage from "./pages/ProfilesListPage";
import ProfileEditorPage from "./pages/ProfileEditorPage";
import SettingsPage from "./pages/SettingsPage";

function navClass({ isActive }: { isActive: boolean }) {
  return `px-3 py-2 rounded-md text-sm font-medium transition-colors ${
    isActive ? "bg-accent text-surface" : "text-ink-dim hover:bg-surface-2 hover:text-ink"
  }`;
}

export default function App() {
  return (
    <div className="min-h-screen bg-bg font-sans text-ink">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <span className="font-display text-lg font-bold text-ink">
            nfogen<span className="font-mono text-sm text-accent">.nfo</span>
          </span>
          <nav className="flex gap-1">
            <NavLink to="/" className={navClass} end>
              Générer
            </NavLink>
            <NavLink to="/profils" className={navClass}>
              Profils
            </NavLink>
            <NavLink to="/gapscan" className={navClass}>
              Scan C411
            </NavLink>
            <NavLink to="/settings" className={navClass}>
              Réglages
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-6">
        {/* key=pathname : une erreur de rendu sur une page ne doit pas rester
            affichee apres avoir navigue ailleurs -- remonte la limite
            d'erreur (et donc reessaie le rendu) a chaque changement de route. */}
        <ErrorBoundary key={useLocation().pathname}>
          <Routes>
            <Route path="/" element={<GeneratePage />} />
            <Route path="/profils" element={<ProfilesListPage />} />
            <Route path="/profiles/new" element={<ProfileEditorPage mode="create" />} />
            <Route path="/profiles/:name" element={<ProfileEditorPage mode="edit" />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/gapscan" element={<GapScanPage />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  );
}
