import { Route, Routes, useLocation } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import Sidebar from "./components/Sidebar";
import GeneratePage from "./pages/GeneratePage";
import LibraryPage from "./pages/LibraryPage";
import ProfilesListPage from "./pages/ProfilesListPage";
import ProfileEditorPage from "./pages/ProfileEditorPage";
import SeedQueuePage from "./pages/SeedQueuePage";
import SettingsPage from "./pages/SettingsPage";
import { ProfileProvider, useProfile } from "./ProfileContext";

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

/** Mobile-first (voir Sidebar.tsx) : empile Sidebar (barre du bas fixe)
 * au-dessus du contenu par defaut, passe en ligne (rail a gauche) a
 * partir de `md:` (768px, convention Tailwind -- s'applique a partir de
 * ce seuil, pas en dessous). `pb-16` reserve la place de la barre du bas
 * fixe sous 768px, retiree des `md:` puisque le rail redevient statique. */
function AppShell() {
  return (
    <div className="flex min-h-screen flex-col bg-bg pb-16 font-sans text-ink md:flex-row md:pb-0">
      <Sidebar />
      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-end border-b border-line bg-surface px-4 py-3">
          <ProfileSelect />
        </header>
        <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6">
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
