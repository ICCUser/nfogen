import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { listAllProfiles, readManagedProfile } from "./api/client";

const STORAGE_KEY = "nfogen.activeProfile";

interface ProfileContextValue {
  profile: string;
  setProfile: (profile: string) => void;
  profiles: Record<string, string[]>;
  /** Nom lisible du profil actif (rules.json -> tracker.display_name),
   * repli sur le nom du profil lui-meme si non declare. */
  displayName: string;
}

const ProfileContext = createContext<ProfileContextValue | null>(null);

/** Etat du "profil actif" partage par toute l'application (entete de
 * App.tsx, page GapScan, page Generer) : "je charge un profil, il
 * definit les regles, le reste de l'appli marche pareil" (retour
 * utilisateur, 2026-08-29) -- un seul selecteur global, pas un par page.
 * Persiste le dernier choix (localStorage) pour ne pas le reperdre a
 * chaque rechargement ; non bloquant si le stockage est indisponible
 * (navigation privee...). */
export function ProfileProvider({ children }: { children: ReactNode }) {
  const [profile, setProfileState] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) || "c411";
    } catch {
      return "c411";
    }
  });
  const [profiles, setProfiles] = useState<Record<string, string[]>>({});
  const [displayName, setDisplayName] = useState(profile);

  useEffect(() => {
    listAllProfiles()
      .then(setProfiles)
      .catch(() => setProfiles({}));
  }, []);

  useEffect(() => {
    readManagedProfile(profile)
      .then((p) => setDisplayName(p.rules.tracker?.display_name ?? profile))
      .catch(() => setDisplayName(profile));
  }, [profile]);

  function setProfile(next: string) {
    setProfileState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // stockage indisponible : le choix ne survit juste pas a un rechargement.
    }
  }

  return (
    <ProfileContext.Provider value={{ profile, setProfile, profiles, displayName }}>
      {children}
    </ProfileContext.Provider>
  );
}

export function useProfile(): ProfileContextValue {
  const ctx = useContext(ProfileContext);
  if (!ctx) throw new Error("useProfile doit être utilisé à l'intérieur de <ProfileProvider>.");
  return ctx;
}
