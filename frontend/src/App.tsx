import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import GeneratePage from "./pages/GeneratePage";
import LibraryPage from "./pages/LibraryPage";
import ProfilesListPage from "./pages/ProfilesListPage";
import ProfileEditorPage from "./pages/ProfileEditorPage";
import SeedQueuePage from "./pages/SeedQueuePage";
import SettingsPage from "./pages/SettingsPage";
import { ProfileProvider, useProfile } from "./ProfileContext";

function navClass({ isActive }: { isActive: boolean }) {
  return `px-3 py-2 rounded-md text-sm font-medium transition-colors ${
    isActive ? "bg-accent text-surface" : "text-ink-dim hover:bg-surface-2 hover:text-ink"
  }`;
}

/** Selecteur unique du profil actif, dans l'entete -- remplace un
 * selecteur par page (retour utilisateur, 2026-08-29 : "je charge un
 * profil, il definit les regles, le reste de l'appli marche pareil"). */
function ProfileSelect() {
  const { profile, setProfile, profiles } = useProfile();
  return (
    <select
      value={profile}
      onChange={(e) => setProfile(e.target.value)}
      aria-label="Profil actif"
      className="rounded-md border border-line-strong bg-surface px-2 py-1.5 text-sm text-ink"
    >
      {Object.keys(profiles).length === 0 && <option value="c411">c411</option>}
      {Object.keys(profiles).map((p) => (
        <option key={p} value={p}>
          {p}
        </option>
      ))}
    </select>
  );
}

function AppShell() {
  return (
    <div className="min-h-screen bg-bg font-sans text-ink">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-3">
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
            <NavLink to="/library" className={navClass}>
              Bibliothèque
            </NavLink>
            <NavLink to="/seed-queue" className={navClass}>
              À mettre en seed
            </NavLink>
            <NavLink to="/settings" className={navClass}>
              Réglages
            </NavLink>
          </nav>
          <ProfileSelect />
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
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
            <Route path="/library" element={<LibraryPage />} />
            <Route path="/seed-queue" element={<SeedQueuePage />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <ProfileProvider>
      <AppShell />
    </ProfileProvider>
  );
}
